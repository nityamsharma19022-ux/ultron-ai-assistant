import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_to_text.dart';

/// Speech recognition, behind an interface so tests can use a fake.
abstract class SpeechInput {
  /// True only where recognition is known to stay on this device. Private
  /// conversations allow voice input only then.
  bool get recognisesOnDevice;

  /// Prepares the recogniser (asks for microphone permission). False when
  /// speech recognition can't be used here.
  Future<bool> initialize();

  Future<void> listen({
    String? localeId,
    required void Function(String text, bool isFinal) onResult,
    required void Function(double level) onLevel,
    required void Function() onDone,
    required void Function(String message) onError,
  });

  /// Stops listening; the words heard so far arrive as a final result.
  Future<void> stop();

  /// Stops listening and discards the result.
  Future<void> cancel();
}

enum SpeakOutcome { spoken, noLocalVoice, failed }

/// Text-to-speech, behind an interface so tests can use a fake.
abstract class SpeechOutput {
  /// Speaks [text] and completes when it has finished or was stopped. With
  /// [localOnly], speaks only with a voice that works offline.
  Future<SpeakOutcome> speak(String text, {required double rate, String? locale, required bool localOnly});

  Future<void> stop();
}

bool get _isWindows => !kIsWeb && defaultTargetPlatform == TargetPlatform.windows;
bool get _isAndroid => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

/// speech_to_text: Windows Speech (SAPI) dictation on Windows, the system
/// recogniser on Android, the browser's Web Speech API on the web.
class PluginSpeechInput implements SpeechInput {
  final _stt = SpeechToText();
  void Function()? _onDone;
  void Function(String)? _onError;

  // SAPI dictation runs locally. On Android the plugin's "on device" option
  // is only a preference: when the phone has no on-device recogniser it
  // quietly uses the default one (usually Google's online service), so
  // ULTRON can't guarantee local recognition there. Browsers use online
  // services too.
  @override
  bool get recognisesOnDevice => _isWindows;

  @override
  Future<bool> initialize() => _stt.initialize(
    onStatus: (status) {
      if (status == SpeechToText.doneStatus) _onDone?.call();
    },
    onError: (SpeechRecognitionError e) => _onError?.call(_errorText(e.errorMsg)),
  );

  @override
  Future<void> listen({
    String? localeId,
    required void Function(String text, bool isFinal) onResult,
    required void Function(double level) onLevel,
    required void Function() onDone,
    required void Function(String message) onError,
  }) async {
    _onDone = onDone;
    _onError = onError;
    await _stt.listen(
      onResult: (r) => onResult(r.recognizedWords, r.finalResult),
      // Android reports roughly -2..10 dB.
      onSoundLevelChange: (db) => onLevel(((db + 2) / 12).clamp(0.0, 1.0)),
      listenOptions: SpeechListenOptions(
        partialResults: true,
        onDevice: true, // preference only; see recognisesOnDevice
        cancelOnError: true,
        listenMode: ListenMode.dictation,
        pauseFor: const Duration(seconds: 3),
        listenFor: const Duration(seconds: 60),
        localeId: localeId,
      ),
    );
  }

  @override
  Future<void> stop() => _stt.stop();

  @override
  Future<void> cancel() => _stt.cancel();

  static String _errorText(String code) => switch (code) {
    'error_no_match' || 'error_speech_timeout' => "Didn't catch that. Try again.",
    'error_permission' || 'error_insufficient_permissions' => 'Microphone permission is needed for voice input.',
    'error_network' || 'error_network_timeout' || 'error_server' => 'The speech service is unreachable.',
    'error_busy' || 'error_recognizer_busy' => 'Speech recognition is busy. Try again in a moment.',
    'error_language_not_supported' || 'error_language_unavailable' => 'This language is not available for speech.',
    _ => 'Speech recognition stopped ($code).',
  };
}

/// flutter_tts: Windows speech synthesis, Android's text-to-speech engine.
class PluginSpeechOutput implements SpeechOutput {
  PluginSpeechOutput() {
    _tts.setCompletionHandler(_finish);
    _tts.setCancelHandler(_finish);
    _tts.setErrorHandler((_) => _finish());
  }

  final _tts = FlutterTts();
  Completer<void>? _speaking;

  void _finish() {
    final c = _speaking;
    _speaking = null;
    if (c != null && !c.isCompleted) c.complete();
  }

  @override
  Future<SpeakOutcome> speak(String text, {required double rate, String? locale, required bool localOnly}) async {
    try {
      await stop();
      await _tts.setSpeechRate(rate);
      if (locale != null) await _tts.setLanguage(locale);
      if (localOnly && !await _useOfflineVoice(locale)) return SpeakOutcome.noLocalVoice;
      final done = _speaking = Completer<void>();
      final started = await _tts.speak(text);
      if (started != 1) {
        _finish();
        return SpeakOutcome.failed;
      }
      await done.future;
      return SpeakOutcome.spoken;
    } on Object {
      _finish();
      return SpeakOutcome.failed;
    }
  }

  /// Windows voices are installed on the PC. Android voices say whether
  /// they need the network; pick one that doesn't. Elsewhere (web), there's
  /// no way to tell, so private replies aren't spoken.
  Future<bool> _useOfflineVoice(String? locale) async {
    if (_isWindows) return true;
    if (!_isAndroid) return false;
    final tag = (locale ?? PlatformDispatcher.instance.locale.toLanguageTag()).replaceAll('_', '-').toLowerCase();
    final language = tag.split('-').first;
    final voices = [
      for (final v in (await _tts.getVoices as List? ?? const []))
        if (v is Map && v['network_required'] == '0') v.map((k, val) => MapEntry('$k', '$val')),
    ];
    String loc(Map<String, String> v) => (v['locale'] ?? '').replaceAll('_', '-').toLowerCase();
    final voice =
        voices.where((v) => loc(v) == tag).firstOrNull ?? voices.where((v) => loc(v).startsWith(language)).firstOrNull;
    if (voice == null) return false;
    await _tts.setVoice({'name': voice['name'] ?? '', 'locale': voice['locale'] ?? ''});
    return true;
  }

  @override
  Future<void> stop() async {
    if (_speaking != null) await _tts.stop();
    _finish();
  }
}
