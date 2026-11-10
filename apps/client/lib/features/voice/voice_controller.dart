import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/settings/app_settings.dart';
import '../chat/chat_controller.dart';
import '../chat/chat_state.dart';
import 'speech_engines.dart';

final speechInputProvider = Provider<SpeechInput>((ref) => PluginSpeechInput());
final speechOutputProvider = Provider<SpeechOutput>((ref) => PluginSpeechOutput());

const privateVoiceInputBlocked =
    "Voice input is off in private conversations on this device: its speech recognition may use an online "
    'service. Type instead, or use ULTRON on your Windows PC.';
const privateNoOfflineVoice = 'No offline voice is installed, so this private reply was not read aloud.';

class VoiceState {
  const VoiceState({
    this.listening = false,
    this.speaking = false,
    this.level = 0,
    this.transcript = '',
    this.notice,
    this.noticeId = 0,
  });

  final bool listening;
  final bool speaking;

  /// Microphone loudness, 0..1 (drives the visualizer).
  final double level;

  /// Words heard so far while listening.
  final String transcript;

  /// Latest message for the user; [noticeId] changes with each one.
  final String? notice;
  final int noticeId;

  VoiceState copyWith({bool? listening, bool? speaking, double? level, String? transcript}) => VoiceState(
    listening: listening ?? this.listening,
    speaking: speaking ?? this.speaking,
    level: level ?? this.level,
    transcript: transcript ?? this.transcript,
    notice: notice,
    noticeId: noticeId,
  );

  VoiceState withNotice(String message) => VoiceState(
    listening: listening,
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
  bool? _available;
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
    await stopSpeaking();
    try {
      _available ??= await _input.initialize();
    } on Object {
      _available = false;
    }
    if (_available != true) return _notice('Speech recognition is not available on this device.');

    final session = ++_listenSession;
    state = state.copyWith(listening: true, transcript: '', level: 0);
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
      );
    } on Object {
      _finishListening(session, send: false);
      _notice('Could not start listening.');
    }
    if (!state.listening) _completeCapture(null);
  }

  /// Stops listening and throws away what was heard.
  Future<void> cancelListening() async {
    if (!state.listening) return;
    _listenSession++;
    state = state.copyWith(listening: false, transcript: '', level: 0);
    _completeCapture(null);
    await _input.cancel();
  }

  void _finishListening(int session, {required bool send}) {
    if (session != _listenSession || !state.listening) return;
    _listenSession++;
    final text = state.transcript.trim();
    state = state.copyWith(listening: false, transcript: '', level: 0);
    if (_capture != null) return _completeCapture(send && text.isNotEmpty ? text : null);
    if (!send || text.isEmpty) return;
    // The chat may have been switched to private while listening.
    if (privateInputBlocked) return _notice(privateVoiceInputBlocked);
    if (ref.read(chatProvider).busy) return _notice('A reply is still running, so "$text" was not sent.');
    ref.read(chatProvider.notifier).send(text);
  }

  // ------------------------------------------------------------- speaking

  void _onChat(ChatState? previous, ChatState next) {
    final before = previous?.conversation?.id;
    if (before != null && before != next.conversation?.id) stopSpeaking();
    // A new message interrupts whatever is being read.
    if (previous != null && !previous.busy && next.busy) stopSpeaking();
    if (previous == null || previous.messages.length != next.messages.length) return;
    final was = previous.messages.lastOrNull;
    final now = next.messages.lastOrNull;
    if (was == null || now == null || was.isUser || now.isUser) return;
    if (was.status == MessageStatus.streaming && now.status == MessageStatus.complete) {
      if (ref.read(settingsProvider).speakReplies) speak(now.content, private: next.isPrivate);
    }
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
        _notice('Could not read the reply aloud.');
      case SpeakOutcome.spoken:
        break;
    }
  }

  Future<void> stopSpeaking() async {
    if (!state.speaking) return;
    _speakSession++;
    state = state.copyWith(speaking: false);
    await _output.stop();
  }
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
