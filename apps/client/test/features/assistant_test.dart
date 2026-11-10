import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/features/assistant/assistant_screen.dart';

import '../support/fake_backend.dart';
import '../support/fake_platform.dart';
import '../support/fake_voice.dart';
import 'tasks_test.dart' show settle;

const _phone = Size(412, 892);

void main() {
  test('dismiss commands', () {
    for (final t in ['stop', 'Never mind', 'go to sleep', 'ULTRON, cancel', 'bye', 'Stop listening.', 'sleep please']) {
      expect(isDismissCommand(t), isTrue, reason: t);
    }
    for (final t in ['stop the music on my phone', 'open spotify', 'cancel my 5pm reminder']) {
      expect(isDismissCommand(t), isFalse, reason: t);
    }
  });

  testWidgets('invoked as the phone assistant: greets, listens, acts, speaks', (tester) async {
    final backend = FakeBackend();
    backend.commandReply = (text) => {
      'type': 'task',
      'message': 'Done. Opened Spotify.',
      'task': backend.task('t', 'Open Spotify on your phone', 'completed', [
        FakeBackend.step('s', 'Open Spotify on your phone', 'succeeded', target: 'android'),
      ]),
    };
    final mic = FakeSpeechInput();
    final speaker = FakeSpeechOutput();
    final assistant = FakeAssistantPlatform(launchedAsAssist: true);
    await pumpUltron(
      tester,
      backend,
      signedIn: true,
      size: _phone,
      speechInput: mic,
      speechOutput: speaker,
      assistantPlatform: assistant,
    );
    await settle(tester);
    expect(find.byKey(const Key('assistant-screen')), findsOneWidget);
    expect(speaker.spoken.first.text, assistantGreeting);
    expect(mic.listenCalls, 1);

    mic.hear('open spotify');
    await tester.pump();
    await tester.tap(find.byKey(const Key('assistant-done')));
    await settle(tester);
    expect(backend.commands, ['open spotify']);
    expect(find.text('"open spotify"'), findsOneWidget);
    expect(find.text('Done. Opened Spotify.'), findsOneWidget);
    expect(speaker.spoken.last.text, 'Done. Opened Spotify.');
  });

  testWidgets('asks for approval and reports the outcome', (tester) async {
    final backend = FakeBackend();
    backend.commandReply = (text) => {
      'type': 'task',
      'message': 'I need your approval to: Organize downloads by type',
      'task': backend.task('t', 'Organize downloads', 'awaiting_approval', [
        FakeBackend.step('s', 'Organize downloads by type', 'awaiting_approval'),
      ]),
    };
    final mic = FakeSpeechInput();
    final speaker = FakeSpeechOutput();
    await pumpUltron(tester, backend, signedIn: true, size: _phone, speechInput: mic, speechOutput: speaker);
    await tester.tap(find.byKey(const Key('open-assistant')));
    await settle(tester);
    mic.hear('organize my downloads');
    await tester.tap(find.byKey(const Key('assistant-done')));
    await settle(tester);
    expect(find.byKey(const Key('assistant-approval')), findsOneWidget);
    await tester.tap(find.byKey(const Key('assistant-approve')));
    await settle(tester, 10);
    expect(find.byKey(const Key('assistant-approval')), findsNothing);
    expect(speaker.spoken.last.text, 'Done.');
  });

  testWidgets('"never mind" closes without doing anything', (tester) async {
    final backend = FakeBackend();
    final mic = FakeSpeechInput();
    await pumpUltron(tester, backend, signedIn: true, size: _phone, speechInput: mic);
    await tester.tap(find.byKey(const Key('open-assistant')));
    await settle(tester);
    mic.hear('never mind');
    await tester.tap(find.byKey(const Key('assistant-done')));
    await settle(tester);
    expect(backend.commands, isEmpty);
    expect(find.byKey(const Key('assistant-screen')), findsNothing);
  });

  testWidgets('nothing heard: says so and offers to ask again', (tester) async {
    final mic = FakeSpeechInput();
    await pumpUltron(tester, FakeBackend(), signedIn: true, size: _phone, speechInput: mic);
    await tester.tap(find.byKey(const Key('open-assistant')));
    await settle(tester);
    await tester.tap(find.byKey(const Key('assistant-done')));
    await settle(tester);
    expect(find.text("I didn't catch that."), findsOneWidget);
    await tester.tap(find.byKey(const Key('assistant-ask')));
    await settle(tester);
    expect(mic.listenCalls, 2);
  });

  testWidgets('a running app opens the assistant when invoked', (tester) async {
    final assistant = FakeAssistantPlatform();
    await pumpUltron(tester, FakeBackend(), signedIn: true, size: _phone, assistantPlatform: assistant);
    expect(find.byKey(const Key('assistant-screen')), findsNothing);
    assistant.invoke();
    await settle(tester);
    expect(find.byKey(const Key('assistant-screen')), findsOneWidget);
  });
}
