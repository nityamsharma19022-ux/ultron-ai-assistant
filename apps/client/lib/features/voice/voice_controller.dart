import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/providers.dart';
import '../../core/settings/app_settings.dart';
import '../chat/chat_controller.dart';
import '../chat/chat_state.dart';
import 'core_speech_input.dart';
import 'speech_engines.dart';

/// Windows: the app records and ULTRON Core transcribes (faster-whisper),
/// because the Windows speech plugin never reports a final result. Android
/// and the web use the device's own recogniser.
final speechInputProvider = Provider<SpeechInput>(
  (ref) => !kIsWeb && defaultTargetPlatform == TargetPlatform.windows
      ? CoreSpeechInput(() => ref.read(apiProvider), RecordPcmRecorder())
      : PluginSpeechInput(),
);
final speechOutputProvider = Provider<SpeechOutput>((ref) => PluginSpeechOutput());

const privateVoiceInputBlocked =
    "Voice input is off in private conversations on this device: its speech recognition may use an online "
    'service. Type instead, or use ULTRON on your Windows PC.';
const privateNoOfflineVoice = 'No offline voice is installed, so this private reply was not read aloud.';

class VoiceState {
  const VoiceState({
    this.listening = false,
    this.transcribing = false,
    this.speaking = false,
    this.level = 0,
    this.transcript = '',
    this.notice,
    this.noticeId = 0,
  });

  final bool listening;

  /// Recording finished; ULTRON is working out the words.
  final bool transcribing;
  final bool speaking;

  /// Microphone loudness, 0..1 (drives the visualizer).
  final double level;

  /// Words heard so far while listening.
  final String transcript;

  /// Latest message for the user; [noticeId] changes with each one.
  final String? notice;
  final int noticeId;

  VoiceState copyWith({bool? listening, bool? transcribing, bool? speaking, double? level, String? transcript}) =>
      VoiceState(
        listening: listening ?? this.listening,
        transcribing: transcribing ?? this.transcribing,
        speaking: speaking ?? this.speaking,
        level: level ?? this.level,
        transcript: transcript ?? this.transcript,
        notice: notice,
        noticeId: noticeId,
      );

  VoiceState withNotice(String message) => VoiceState(
    listening: listening,
    transcribing: transcribing,
    speaking: speaking,
    level: level,
    transcript: transcript,
    notice: message,
    noticeId: noticeId + 1,
  );
}

final voiceProvider = NotifierProvider<VoiceController, VoiceState>(VoiceController.new);

/// Push-to-talk and read-aloud.
///
/// Privacy rules: in a private conversation, voice input is allowed only
/// where recognition stays on the device, and replies are read aloud only
/// with an offline voice.
class VoiceController extends Notifier<VoiceState> {
  /// Listening always ends after this, even if the recogniser never reports
  /// back (the Windows plugin could leave the mic "listening" forever).
  static Duration watchdog = const Duration(seconds: 75);

  bool _available = false;
  Timer? _watchdog;
  int _listenSession = 0;
  int _speakSession = 0;
  // Set while the assistant screen listens: the words go there, not to chat.
  Completer<String?>? _capture;

  SpeechInput get _input => ref.read(speechInputProvider);
  SpeechOutput get _output => ref.read(speechOutputProvider);

  @override
  VoiceState build() {
    ref.listen(chatProvider, _onChat);
    ref.onDispose(() {
      _listenSession++;
      _speakSession++;
      _watchdog?.cancel();
    });
    return const VoiceState();
  }

  void _notice(String message) => state = state.withNotice(message);

  bool get privateInputBlocked => ref.read(chatProvider).isPrivate && !_input.recognisesOnDevice;

  // ------------------------------------------------------------ listening

  /// Mic button: starts listening, or finishes and sends what was heard.
  Future<void> toggleListening() async {
    if (state.listening) {
      await _input.stop();
      return;
    }
    if (privateInputBlocked) return _notice(privateVoiceInputBlocked);
    if (ref.read(chatProvider).busy) return _notice('Wait for the reply to finish, or stop it first.');
    await _startListening();
  }

  /// Listens once for the assistant screen and returns what was heard (null
  /// if nothing was heard, it was cancelled, or speech isn't available).
  Future<String?> capture() async {
    if (state.listening) return null;
    final completer = _capture = Completer<String?>();
    await _startListening();
    if (!state.listening && !completer.isCompleted) {
      _capture = null;
      completer.complete(null);
    }
    return completer.future;
  }

  /// Ends an assistant capture early and uses the words heard so far.
  Future<void> finishCapture() async {
    if (state.listening) await _input.stop();
  }

  void _completeCapture(String? text) {
    final c = _capture;
    _capture = null;
    if (c != null && !c.isCompleted) c.complete(text);
  }

  Future<void> _startListening() async {
    // Instant feedback: the listening state and a sound before anything slow.
    final session = ++_listenSession;
    state = state.copyWith(listening: true, transcribing: false, transcript: '', level: 0);
    _feedback(start: true);
    await stopSpeaking();
    if (!_available) {
      // Not cached when it fails: fixing mic permission works without a restart.
      try {
        _available = await _input.initialize();
      } on Object {
        _available = false;
      }
    }
    if (session != _listenSession) return;
    if (!_available) {
      _listenSession++;
      state = state.copyWith(listening: false, transcript: '', level: 0);
      return _notice('Speech recognition is not available on this device. Check microphone access.');
    }
    _watchdog?.cancel();
    _watchdog = Timer(watchdog, () => _onWatchdog(session));
    try {
      await _input.listen(
        localeId: ref.read(settingsProvider).voiceLocale,
        onResult: (text, isFinal) {
          if (session != _listenSession || !state.listening) return;
          state = state.copyWith(transcript: text);
          if (isFinal) _finishListening(session, send: true);
        },
        onLevel: (level) {
          if (session == _listenSession && state.listening) state = state.copyWith(level: level);
        },
        onDone: () => _finishListening(session, send: true),
        onError: (message) {
          if (session != _listenSession || !state.listening) return;
          _finishListening(session, send: false);
          _notice(message);
        },
        onProcessing: () {
          if (session == _listenSession && state.listening) state = state.copyWith(transcribing: true, level: 0);
        },
      );
    } on Object {
      _finishListening(session, send: false);
      _notice('Could not start listening.');
    }
    if (!state.listening) _completeCapture(null);
  }

  void _onWatchdog(int session) {
    if (session != _listenSession || !state.listening) return;
    final heard = state.transcript.trim().isNotEmpty;
    unawaited(_input.cancel());
    _finishListening(session, send: heard);
    if (!heard) _notice('Listening stopped: no words were recognised. Try again.');
  }

  /// Short, instant confirmation that the mic opened or closed.
  void _feedback({required bool start}) {
    try {
      if (defaultTargetPlatform == TargetPlatform.android) {
        unawaited(HapticFeedback.lightImpact());
        unawaited(SystemSound.play(SystemSoundType.click));
      } else if (start) {
        unawaited(SystemSound.play(SystemSoundType.alert));
      }
    } on Object {
      // Sound is optional.
    }
  }

  /// Stops listening and throws away what was heard.
  Future<void> cancelListening() async {
    if (!state.listening) return;
    _listenSession++;
    _watchdog?.cancel();
    state = state.copyWith(listening: false, transcribing: false, transcript: '', level: 0);
    _completeCapture(null);
    await _input.cancel();
  }

  void _finishListening(int session, {required bool send}) {
    if (session != _listenSession || !state.listening) return;
    _listenSession++;
    _watchdog?.cancel();
    final text = state.transcript.trim();
    state = state.copyWith(listening: false, transcribing: false, transcript: '', level: 0);
    if (send && text.isNotEmpty) _feedback(start: false);
    if (_capture != null) return _completeCapture(send && text.isNotEmpty ? text : null);
    if (!send || text.isEmpty) return;
    // The chat may have been switched to private while listening.
    if (privateInputBlocked) return _notice(privateVoiceInputBlocked);
    if (ref.read(chatProvider).busy) return _notice('A reply is still running, so "$text" was not sent.');
    ref.read(chatProvider.notifier).send(text);
  }

  // ------------------------------------------------------------- speaking

  // Streaming read-aloud: sentences are spoken as soon as they are complete.
  String? _readingId;
  int _spokenUpTo = 0;
  final _queue = <String>[];
  bool _private = false;

  void _onChat(ChatState? previous, ChatState next) {
    final before = previous?.conversation?.id;
    if (before != null && before != next.conversation?.id) stopSpeaking();
    // A new message interrupts whatever is being read.
    if (previous != null && !previous.busy && next.busy) stopSpeaking();
    if (!ref.read(settingsProvider).speakReplies) return;
    final now = next.messages.lastOrNull;
    if (now == null || now.isUser) return;
    if (now.status == MessageStatus.cancelled) {
      if (_readingId == now.id) stopSpeaking();
      return;
    }
    final streaming = now.status == MessageStatus.streaming;
    final finished = now.status == MessageStatus.complete;
    if (!streaming && !finished) return;
    if (_readingId != now.id) {
      // Only replies that stream in while we watch are read (not history).
      final was = previous?.messages.lastOrNull;
      if (!(streaming || (was != null && !was.isUser && was.status == MessageStatus.streaming))) return;
      _readingId = now.id;
      _spokenUpTo = 0;
      _private = next.isPrivate;
    }
    final upTo = finished ? now.content.length : speakableBoundary(now.content, _spokenUpTo);
    if (upTo <= _spokenUpTo) return;
    final chunk = speakableText(now.content.substring(_spokenUpTo, upTo));
    _spokenUpTo = upTo;
    if (chunk.isNotEmpty) _enqueue(chunk);
  }

  void _enqueue(String text) {
    if (state.listening) return;
    _queue.add(text);
    if (!state.speaking) unawaited(_drain(++_speakSession));
  }

  Future<void> _drain(int session) async {
    final settings = ref.read(settingsProvider);
    state = state.copyWith(speaking: true);
    while (_queue.isNotEmpty && session == _speakSession) {
      final outcome = await _output.speak(
        _queue.removeAt(0),
        rate: settings.speechRate,
        locale: settings.voiceLocale,
        localOnly: _private,
      );
      if (session != _speakSession) return;
      if (outcome != SpeakOutcome.spoken) {
        _queue.clear();
        _notice(
          outcome == SpeakOutcome.noLocalVoice
              ? privateNoOfflineVoice
              : "Couldn't speak: no text-to-speech voice is available on this device.",
        );
      }
    }
    if (session == _speakSession) state = state.copyWith(speaking: false);
  }

  /// Reads [text] aloud with the user's voice settings.
  Future<void> speak(String text, {required bool private}) async {
    final spoken = speakableText(text);
    if (spoken.isEmpty || state.listening) return;
    await stopSpeaking();
    final session = ++_speakSession;
    final settings = ref.read(settingsProvider);
    state = state.copyWith(speaking: true);
    final outcome = await _output.speak(
      spoken,
      rate: settings.speechRate,
      locale: settings.voiceLocale,
      localOnly: private,
    );
    if (session != _speakSession) return;
    state = state.copyWith(speaking: false);
    switch (outcome) {
      case SpeakOutcome.noLocalVoice:
        _notice(privateNoOfflineVoice);
      case SpeakOutcome.failed:
        _notice("Couldn't speak: no text-to-speech voice is available on this device.");
      case SpeakOutcome.spoken:
        break;
    }
  }

  Future<void> stopSpeaking() async {
    _queue.clear();
    // Whatever is still streaming in is not read any more.
    if (_readingId != null) _spokenUpTo = 1 << 30;
    if (!state.speaking) return;
    _speakSession++;
    state = state.copyWith(speaking: false);
    await _output.stop();
  }
}

/// Where the text from [from] can be read up to: just after the last complete
/// sentence (., !, ?, Hindi ।, or a line break), never inside an unfinished
/// code block, and only once there are a few words to say. Returns [from]
/// when nothing is ready yet.
int speakableBoundary(String text, int from, {int minChars = 12}) {
  if (from >= text.length) return from;
  var end = from;
  final re = RegExp(r'[.!?।](?=\s)|\n');
  for (final m in re.allMatches(text, from)) {
    final cut = m.end;
    // Inside an open ``` block: wait until it closes.
    if ('```'.allMatches(text.substring(0, cut)).length.isOdd) break;
    end = cut;
  }
  if (end - from < minChars) return from;
  return end;
}

/// Text to read aloud: code blocks and Markdown markers removed, links
/// reduced to their text, cut to a length speech engines accept.
String speakableText(String text, {int maxLength = 3500}) {
  var t = text
      .replaceAll(RegExp(r'```[\s\S]*?(```|$)'), ' (code omitted) ')
      .replaceAllMapped(RegExp(r'\[([^\]]+)\]\([^)]*\)'), (m) => m[1]!)
      .replaceAll(RegExp(r'https?://\S+'), 'link')
      .replaceAll(RegExp(r'^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+', multiLine: true), '')
      .replaceAll(RegExp(r'[*_`~#|]'), '')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  if (t.length > maxLength) {
    final cut = t.lastIndexOf(RegExp(r'[.!?]\s'), maxLength);
    t = '${t.substring(0, cut > maxLength ~/ 2 ? cut + 1 : maxLength).trim()} The rest is on screen.';
  }
  return t;
}
