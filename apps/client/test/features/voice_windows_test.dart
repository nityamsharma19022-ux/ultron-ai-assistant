import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/api/command_models.dart';
import 'package:ultron_app/core/api/ultron_api.dart';
import 'package:ultron_app/core/auth/token_store.dart';
import 'package:ultron_app/features/voice/core_speech_input.dart';
import 'package:ultron_app/features/voice/voice_controller.dart';

import '../support/fake_backend.dart';
import '../support/fake_voice.dart';
import 'chat_test.dart' show drain;
import 'voice_test.dart' show tapMic;

class FakePcm implements PcmRecorder {
  StreamController<Uint8List>? _c;
  int stops = 0;

  @override
  Future<bool> hasPermission() async => true;

  @override
  Future<Stream<Uint8List>> start() async => (_c = StreamController<Uint8List>()).stream;

  @override
  Future<void> stop() async {
    stops++;
    await _c?.close();
  }

  /// [ms] milliseconds of a tone (speech) or silence at 16 kHz.
  void feed(int ms, {bool speech = true}) {
    final n = 16 * ms;
    final b = ByteData(n * 2);
    for (var i = 0; i < n; i++) {
      final v = speech ? (0.3 * 32767 * math.sin(2 * math.pi * 300 * i / 16000)).round() : 0;
      b.setInt16(i * 2, v, Endian.little);
    }
    _c?.add(b.buffer.asUint8List());
  }
}

class FakeApi extends UltronApi {
  FakeApi() : super(baseUrl: 'http://core.test', tokens: MemoryTokenStore());
  final sent = <(Uint8List, String?)>[];
  String reply = 'open notepad';

  @override
  Future<Transcript> transcribe(List<int> wav, {String? language, bool retry = true}) async {
    sent.add((Uint8List.fromList(wav), language));
    return Transcript(text: reply, language: 'en', seconds: 1.2);
  }
}

typedef Calls = ({List<String> results, List<String> errors, int done, int processing});

Future<(CoreSpeechInput, FakePcm, FakeApi, Calls Function())> startListening({String? locale}) async {
  final pcm = FakePcm();
  final api = FakeApi();
  final input = CoreSpeechInput(() => api, pcm);
  final results = <String>[], errors = <String>[];
  var done = 0, processing = 0;
  await input.listen(
    localeId: locale,
    onResult: (t, isFinal) => results.add('$t|$isFinal'),
    onLevel: (_) {},
    onDone: () => done++,
    onError: errors.add,
    onProcessing: () => processing++,
  );
  return (input, pcm, api, () => (results: results, errors: errors, done: done, processing: processing));
}

void main() {
  test('Windows recorder: stops after a pause and sends a 16 kHz WAV to Core', () async {
    final (_, pcm, api, calls) = await startListening(locale: 'hi_IN');
    pcm.feed(800); // speech
    pcm.feed(600, speech: false);
    await Future<void>.delayed(Duration.zero);
    expect(api.sent, isEmpty); // 0.6 s pause: still listening
    pcm.feed(700, speech: false); // 1.3 s pause: done
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(api.sent, hasLength(1));
    final (wav, language) = api.sent.single;
    expect(String.fromCharCodes(wav.sublist(0, 4)), 'RIFF');
    expect(ByteData.sublistView(wav).getUint32(24, Endian.little), 16000);
    expect(language, 'hi_IN');
    final c = calls();
    expect(c.processing, 1);
    expect(c.results, ['open notepad|true']);
    expect(c.done, 1);
    expect(pcm.stops, greaterThanOrEqualTo(1));
  });

  test('Windows recorder: silence is never sent to Core', () async {
    final (_, pcm, api, calls) = await startListening();
    pcm.feed(8100, speech: false); // 8 s without speech ends listening
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(api.sent, isEmpty);
    expect(calls().errors.single, contains("Didn't hear anything"));
  });

  test('Windows recorder: pressing the mic again sends what was said', () async {
    final (input, pcm, api, calls) = await startListening();
    pcm.feed(500);
    await Future<void>.delayed(Duration.zero);
    await input.stop();
    expect(api.sent, hasLength(1));
    expect(calls().results, ['open notepad|true']);
    // Cancel discards without sending.
    final (input2, pcm2, api2, _) = await startListening();
    pcm2.feed(500);
    await Future<void>.delayed(Duration.zero);
    await input2.cancel();
    expect(api2.sent, isEmpty);
  });

  testWidgets('listening can never get stuck (watchdog)', (tester) async {
    final old = VoiceController.watchdog;
    VoiceController.watchdog = const Duration(seconds: 3);
    addTearDown(() => VoiceController.watchdog = old);
    final mic = FakeSpeechInput()..silentStop = true;
    await pumpUltron(tester, FakeBackend(), signedIn: true, speechInput: mic);
    await tapMic(tester);
    expect(find.byKey(const Key('listening-bar')), findsOneWidget);
    await tapMic(tester); // the plugin ignores this (Windows bug)
    expect(find.byKey(const Key('listening-bar')), findsOneWidget);
    await tester.pump(const Duration(seconds: 3));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const Key('listening-bar')), findsNothing);
    expect(find.textContaining('Listening stopped'), findsOneWidget);
  });

  testWidgets('shows Transcribing… while Core works out the words', (tester) async {
    final mic = FakeSpeechInput();
    await pumpUltron(tester, FakeBackend(), signedIn: true, speechInput: mic);
    await tapMic(tester);
    expect(find.text('Listening… tap the mic again to send'), findsOneWidget);
    mic.processing();
    await tester.pump();
    expect(find.text('Transcribing…'), findsOneWidget);
    mic.hear('open notepad');
    await mic.stop();
    await drain(tester); // the words are sent to chat; let the reply finish
    expect(find.byKey(const Key('listening-bar')), findsNothing);
  });
}
