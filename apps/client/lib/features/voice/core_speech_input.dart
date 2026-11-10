import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:record/record.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/ultron_api.dart';
import 'speech_engines.dart';

/// Raw 16 kHz mono PCM from the microphone (behind an interface for tests).
abstract class PcmRecorder {
  Future<bool> hasPermission();
  Future<Stream<Uint8List>> start();
  Future<void> stop();
}

class RecordPcmRecorder implements PcmRecorder {
  final _recorder = AudioRecorder();

  @override
  Future<bool> hasPermission() => _recorder.hasPermission();

  @override
  Future<Stream<Uint8List>> start() => _recorder.startStream(
    const RecordConfig(encoder: AudioEncoder.pcm16bits, sampleRate: CoreSpeechInput.sampleRate, numChannels: 1),
  );

  @override
  Future<void> stop() async {
    await _recorder.stop();
  }
}

/// Voice input for Windows: records the microphone in the app and lets
/// ULTRON Core transcribe it (faster-whisper, on the user's PC). Listening
/// ends by itself after a short pause, after [maxDuration], or when the mic
/// button is pressed again, so it can never get stuck.
class CoreSpeechInput implements SpeechInput {
  CoreSpeechInput(this._api, this._recorder);

  static const sampleRate = 16000;
  static const maxDuration = Duration(seconds: 30);
  static const noSpeechTimeout = Duration(seconds: 8);
  static const endOfSpeechSilence = Duration(milliseconds: 1200);
  static const speechThreshold = 0.02; // RMS of normalised samples

  final UltronApi Function() _api;
  final PcmRecorder _recorder;

  StreamSubscription<Uint8List>? _sub;
  BytesBuilder? _pcm;
  Timer? _timer;
  _Session? _session;

  /// Transcription runs in ULTRON Core on the user's own PC.
  @override
  bool get recognisesOnDevice => true;

  @override
  Future<bool> initialize() async {
    try {
      return await _recorder.hasPermission();
    } on Object {
      return false;
    }
  }

  @override
  Future<void> listen({
    String? localeId,
    required void Function(String text, bool isFinal) onResult,
    required void Function(double level) onLevel,
    required void Function() onDone,
    required void Function(String message) onError,
    void Function()? onProcessing,
  }) async {
    await _halt();
    final session = _session = _Session(localeId, onResult, onDone, onError, onProcessing);
    _pcm = BytesBuilder(copy: false);
    final Stream<Uint8List> stream;
    try {
      stream = await _recorder.start();
    } on Object {
      _session = null;
      onError('The microphone could not be opened. Check Windows Settings → Privacy → Microphone.');
      return;
    }
    // Pauses are measured in audio received (not wall-clock time).
    int samplesOf(Duration d) => sampleRate * d.inMilliseconds ~/ 1000;
    var samples = 0;
    int? lastVoice;
    _sub = stream.listen((chunk) {
      if (!identical(_session, session)) return;
      _pcm?.add(chunk);
      samples += chunk.length ~/ 2;
      final level = _rms(chunk);
      onLevel(math.min(1, level * 6));
      if (level >= speechThreshold) {
        lastVoice = samples;
        session.heardSpeech = true;
      }
      final silentFor = samples - (lastVoice ?? 0);
      if ((lastVoice != null && silentFor >= samplesOf(endOfSpeechSilence)) ||
          (lastVoice == null && samples >= samplesOf(noSpeechTimeout)) ||
          samples >= samplesOf(maxDuration)) {
        unawaited(_finish(session));
      }
    });
    // Backup in case the microphone stops delivering audio.
    _timer = Timer(maxDuration + const Duration(seconds: 2), () => _finish(session));
  }

  @override
  Future<void> stop() async {
    final s = _session;
    if (s != null) await _finish(s);
  }

  @override
  Future<void> cancel() async {
    _session = null;
    await _halt();
  }

  Future<void> _halt() async {
    _timer?.cancel();
    _timer = null;
    await _sub?.cancel();
    _sub = null;
    try {
      await _recorder.stop();
    } on Object {
      // Already stopped.
    }
  }

  Future<void> _finish(_Session session) async {
    if (!identical(_session, session) || session.finishing) return;
    session.finishing = true;
    await _halt();
    final pcm = _pcm?.takeBytes() ?? Uint8List(0);
    _pcm = null;
    if (!identical(_session, session)) return;
    if (!session.heardSpeech || pcm.length < sampleRate * 2 ~/ 5) {
      // Silence (or under 0.2 s): nothing worth sending to Core.
      _session = null;
      session.onError("Didn't hear anything. Try again a little closer to the mic.");
      return;
    }
    session.onProcessing?.call();
    try {
      final result = await _api().transcribe(wavFromPcm16(pcm, sampleRate), language: session.localeId);
      if (!identical(_session, session)) return;
      _session = null;
      if (result.text.trim().isEmpty) {
        session.onError("Didn't catch that. Try again.");
      } else {
        session.onResult(result.text.trim(), true);
        session.onDone();
      }
    } on ApiException catch (e) {
      if (!identical(_session, session)) return;
      _session = null;
      session.onError(e.message);
    }
  }

  /// Loudness of 16-bit little-endian samples, 0..1.
  static double _rms(Uint8List chunk) {
    final n = chunk.length ~/ 2;
    if (n == 0) return 0;
    final data = ByteData.sublistView(chunk);
    var sum = 0.0;
    for (var i = 0; i < n; i++) {
      final s = data.getInt16(i * 2, Endian.little) / 32768.0;
      sum += s * s;
    }
    return math.sqrt(sum / n);
  }
}

class _Session {
  _Session(this.localeId, this.onResult, this.onDone, this.onError, this.onProcessing);
  final String? localeId;
  final void Function(String text, bool isFinal) onResult;
  final void Function() onDone;
  final void Function(String message) onError;
  final void Function()? onProcessing;
  bool finishing = false;
  bool heardSpeech = false;
}

/// Wraps raw 16-bit mono PCM in a WAV header.
Uint8List wavFromPcm16(Uint8List pcm, int sampleRate) {
  final header = ByteData(44);
  void ascii(int offset, String s) {
    for (var i = 0; i < s.length; i++) {
      header.setUint8(offset + i, s.codeUnitAt(i));
    }
  }

  ascii(0, 'RIFF');
  header.setUint32(4, 36 + pcm.length, Endian.little);
  ascii(8, 'WAVE');
  ascii(12, 'fmt ');
  header.setUint32(16, 16, Endian.little);
  header.setUint16(20, 1, Endian.little); // PCM
  header.setUint16(22, 1, Endian.little); // mono
  header.setUint32(24, sampleRate, Endian.little);
  header.setUint32(28, sampleRate * 2, Endian.little);
  header.setUint16(32, 2, Endian.little);
  header.setUint16(34, 16, Endian.little);
  ascii(36, 'data');
  header.setUint32(40, pcm.length, Endian.little);
  return (BytesBuilder(copy: false)
        ..add(header.buffer.asUint8List())
        ..add(pcm))
      .takeBytes();
}
