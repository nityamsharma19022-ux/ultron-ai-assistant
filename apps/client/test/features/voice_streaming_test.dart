import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/api/models.dart';
import 'package:ultron_app/features/chat/chat_controller.dart';
import 'package:ultron_app/features/voice/voice_controller.dart';

import '../support/fake_backend.dart';
import '../support/fake_voice.dart';
import 'chat_test.dart' show drain, sendViaUi;

List<(String, Map<String, dynamic>)> script(List<String> deltas) => [
  ('provider.selected', {'provider': 'groq', 'kind': 'cloud', 'model': 'm', 'fallback_used': false, 'attempts': []}),
  ('status', {'phase': 'generating', 'provider': 'groq', 'kind': 'cloud', 'model': 'm'}),
  for (final d in deltas) ('delta', {'text': d}),
];

void main() {
  test('sentence boundaries: complete sentences only, Hindi danda, no split code blocks', () {
    const t = 'Good evening, Sir. Here is more';
    expect(t.substring(0, speakableBoundary(t, 0)), 'Good evening, Sir.');
    expect(speakableBoundary('Hi. There', 0), 0); // too short to start yet
    const hi = 'नमस्ते सर, आपका दिन कैसा रहा। अगला';
    expect(hi.substring(0, speakableBoundary(hi, 0)), 'नमस्ते सर, आपका दिन कैसा रहा।');
    const code = 'Run this command now. ```\nls -la. more\n';
    expect(code.substring(0, speakableBoundary(code, 0)), 'Run this command now.');
    expect(speakableBoundary('Version 3.14 is out', 0), 0); // a decimal point is not a sentence end
  });

  testWidgets('starts speaking after the first sentence, while the reply streams', (tester) async {
    final speaker = FakeSpeechOutput();
    final backend = FakeBackend()
      ..replyScript = (_, _) =>
          script(['Good evening, Sir. ', 'The second sentence ', 'is still arriving', ' and ends here. Last bit']);
    final app = await pumpUltron(
      tester,
      backend,
      signedIn: true,
      speechOutput: speaker,
      prefs: {'speak_replies': true},
    );
    await sendViaUi(tester, 'Hello');
    // Let only the first few events through (each takes ~20 ms in the fake).
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    final chat = app.container.read(chatProvider);
    expect(chat.messages.last.status, MessageStatus.streaming);
    expect(speaker.spoken.map((s) => s.text), ['Good evening, Sir.']);
    await drain(tester);
    expect(speaker.spoken.map((s) => s.text), [
      'Good evening, Sir.',
      'The second sentence is still arriving and ends here.',
      'Last bit',
    ]);
  });

  testWidgets('talking or stopping cancels the rest of the reply', (tester) async {
    final speaker = FakeSpeechOutput()..holdSpeech = true;
    final backend = FakeBackend()
      ..replyScript = (_, _) => script(['First sentence is here. ', 'Second sentence follows. ', 'Third.']);
    final app = await pumpUltron(
      tester,
      backend,
      signedIn: true,
      speechOutput: speaker,
      prefs: {'speak_replies': true},
    );
    await sendViaUi(tester, 'Hello');
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    expect(app.container.read(voiceProvider).speaking, isTrue);
    await app.container.read(voiceProvider.notifier).stopSpeaking();
    await drain(tester);
    expect(speaker.spoken.map((s) => s.text), ['First sentence is here.']); // nothing more after stop
    expect(app.container.read(voiceProvider).speaking, isFalse);
  });
}
