import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/features/visualizer/ai_visualizer.dart';
import 'package:ultron_app/features/visualizer/visualizer_mode.dart';
import 'package:ultron_app/features/voice/speech_engines.dart';
import 'package:ultron_app/features/voice/voice_controller.dart';

import '../support/fake_backend.dart';
import '../support/fake_voice.dart';
import 'chat_test.dart' show drain, sendViaUi;

AiVisualizer visualizer(WidgetTester tester) => tester.widget<AiVisualizer>(find.byType(AiVisualizer).first);

Future<void> tapMic(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('mic-button')));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 250));
}

Future<void> makePrivate(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('private-toggle')));
  await tester.pump();
}

void main() {
  group('push-to-talk', () {
    testWidgets('shows what is heard and sends it on the second tap', (tester) async {
      final backend = FakeBackend();
      final mic = FakeSpeechInput();
      await pumpUltron(tester, backend, signedIn: true, speechInput: mic);

      await tapMic(tester);
      expect(mic.listenCalls, 1);
      expect(find.byKey(const Key('listening-bar')), findsOneWidget);
      expect(visualizer(tester).mode, VisualizerMode.listening);

      mic.hear('What is on my calendar');
      await tester.pump();
      expect(find.text('What is on my calendar'), findsOneWidget);

      await tapMic(tester); // stop -> final result -> send
      await drain(tester);
      expect(mic.stopCalls, 1);
      expect(find.byKey(const Key('listening-bar')), findsNothing);
      expect(backend.messages.values.expand((m) => m).any((m) => m['content'] == 'What is on my calendar'), isTrue);
      expect(find.text('Hello from ULTRON'), findsOneWidget);
    });

    testWidgets('microphone level drives the visualizer', (tester) async {
      final mic = FakeSpeechInput();
      await pumpUltron(tester, FakeBackend(), signedIn: true, speechInput: mic);
      await tapMic(tester);
      mic.level(0.8);
      await tester.pump();
      expect(visualizer(tester).level, 0.8);
    });

    testWidgets('cancel throws the words away', (tester) async {
      final backend = FakeBackend();
      final mic = FakeSpeechInput();
      await pumpUltron(tester, backend, signedIn: true, speechInput: mic);
      await tapMic(tester);
      mic.hear('never mind');
      await tester.pump();
      await tester.tap(find.byKey(const Key('cancel-listening')));
      await drain(tester);
      expect(mic.cancelCalls, 1);
      expect(backend.conversations, isEmpty);
      expect(find.byKey(const Key('listening-bar')), findsNothing);
    });

    testWidgets('recogniser errors are shown and listening stops', (tester) async {
      final mic = FakeSpeechInput();
      await pumpUltron(tester, FakeBackend(), signedIn: true, speechInput: mic);
      await tapMic(tester);
      mic.fail("Didn't catch that. Try again.");
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text("Didn't catch that. Try again."), findsOneWidget);
      expect(find.byKey(const Key('listening-bar')), findsNothing);
    });

    testWidgets('explains when speech recognition is unavailable', (tester) async {
      final mic = FakeSpeechInput(available: false);
      await pumpUltron(tester, FakeBackend(), signedIn: true, speechInput: mic);
      await tapMic(tester);
      expect(find.text('Speech recognition is not available on this device. Check microphone access.'), findsOneWidget);
      expect(mic.listenCalls, 0);
      // A failure isn't remembered: after fixing mic access it works without a restart.
      mic.available = true;
      for (var i = 0; i < 8; i++) {
        await tester.pump(const Duration(seconds: 1)); // let the message close
      }
      await tapMic(tester);
      expect(mic.initCalls, 2);
      expect(mic.listenCalls, 1);
    });
  });

  group('private conversations', () {
    testWidgets('voice input is blocked where recognition may be online', (tester) async {
      final mic = FakeSpeechInput(recognisesOnDevice: false);
      await pumpUltron(tester, FakeBackend(), signedIn: true, speechInput: mic);
      await makePrivate(tester);
      expect(
        find.descendant(of: find.byKey(const Key('mic-button')), matching: find.byIcon(Icons.mic_off_outlined)),
        findsOneWidget,
      );
      await tapMic(tester);
      expect(mic.initCalls, 0);
      expect(mic.listenCalls, 0);
      expect(find.text(privateVoiceInputBlocked), findsOneWidget);
    });

    testWidgets('voice input works where recognition is on the device', (tester) async {
      final mic = FakeSpeechInput(recognisesOnDevice: true);
      await pumpUltron(tester, FakeBackend(), signedIn: true, speechInput: mic);
      await makePrivate(tester);
      await tapMic(tester);
      expect(mic.listenCalls, 1);
    });

    testWidgets('switching to private while listening does not send', (tester) async {
      final backend = FakeBackend();
      final mic = FakeSpeechInput(recognisesOnDevice: false);
      await pumpUltron(tester, backend, signedIn: true, speechInput: mic);
      await tapMic(tester);
      mic.hear('secret plans');
      await makePrivate(tester);
      await tapMic(tester);
      await drain(tester);
      expect(backend.conversations, isEmpty);
      expect(find.text(privateVoiceInputBlocked), findsOneWidget);
    });
  });

  group('read aloud', () {
    testWidgets('reads finished replies when enabled', (tester) async {
      final speaker = FakeSpeechOutput();
      await pumpUltron(tester, FakeBackend(), signedIn: true, speechOutput: speaker, prefs: {'speak_replies': true});
      await sendViaUi(tester, 'Hi');
      await drain(tester);
      expect(speaker.spoken.single.text, 'Hello from ULTRON');
      expect(speaker.spoken.single.localOnly, isFalse);
    });

    testWidgets('stays quiet when disabled', (tester) async {
      final speaker = FakeSpeechOutput();
      await pumpUltron(tester, FakeBackend(), signedIn: true, speechOutput: speaker);
      await sendViaUi(tester, 'Hi');
      await drain(tester);
      expect(speaker.spoken, isEmpty);
    });

    testWidgets('private replies need an offline voice', (tester) async {
      final speaker = FakeSpeechOutput();
      await pumpUltron(tester, FakeBackend(), signedIn: true, speechOutput: speaker, prefs: {'speak_replies': true});
      await makePrivate(tester);
      await sendViaUi(tester, 'Hi');
      await drain(tester);
      expect(speaker.spoken.single.localOnly, isTrue);
    });

    testWidgets('says so when no offline voice is installed', (tester) async {
      final speaker = FakeSpeechOutput()..outcome = SpeakOutcome.noLocalVoice;
      await pumpUltron(tester, FakeBackend(), signedIn: true, speechOutput: speaker, prefs: {'speak_replies': true});
      await makePrivate(tester);
      await sendViaUi(tester, 'Hi');
      await drain(tester);
      expect(find.text(privateNoOfflineVoice), findsOneWidget);
    });

    testWidgets('the mic button turns into stop-reading while speaking', (tester) async {
      final speaker = FakeSpeechOutput()..holdSpeech = true;
      await pumpUltron(tester, FakeBackend(), signedIn: true, speechOutput: speaker, prefs: {'speak_replies': true});
      await sendViaUi(tester, 'Hi');
      await drain(tester);
      expect(find.byKey(const Key('stop-speaking')), findsOneWidget);
      expect(visualizer(tester).mode, VisualizerMode.speaking);

      await tester.tap(find.byKey(const Key('stop-speaking')));
      await tester.pump();
      expect(speaker.stopCalls, 1);
      expect(find.byKey(const Key('mic-button')), findsOneWidget);
    });

    testWidgets('starting to talk stops reading', (tester) async {
      final speaker = FakeSpeechOutput()..holdSpeech = true;
      final mic = FakeSpeechInput();
      final app = await pumpUltron(
        tester,
        FakeBackend(),
        signedIn: true,
        speechInput: mic,
        speechOutput: speaker,
        prefs: {'speak_replies': true},
      );
      await sendViaUi(tester, 'Hi');
      await drain(tester);
      expect(app.container.read(voiceProvider).speaking, isTrue);

      // E.g. a keyboard shortcut or the visualizer starting to listen.
      await app.container.read(voiceProvider.notifier).toggleListening();
      await tester.pump();
      expect(speaker.stopCalls, 1);
      expect(app.container.read(voiceProvider).speaking, isFalse);
      expect(mic.listenCalls, 1);
      expect(find.byKey(const Key('listening-bar')), findsOneWidget);
    });
  });

  group('speakableText', () {
    test('drops code blocks and markdown, keeps link text', () {
      expect(
        speakableText('## Steps\n1. Run **this**:\n```bash\nls -la\n```\nSee [the docs](https://x.y/z) or https://a.b'),
        'Steps Run this: (code omitted) See the docs or link',
      );
    });

    test('cuts long text at a sentence', () {
      final long = List.filled(50, 'This is a sentence.').join(' ');
      final out = speakableText(long, maxLength: 100);
      expect(out, endsWith('This is a sentence. The rest is on screen.'));
      expect(out.length, lessThan(150));
    });
  });
}
