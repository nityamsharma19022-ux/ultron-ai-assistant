import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/api/models.dart';
import 'package:ultron_app/features/chat/chat_controller.dart';
import 'package:ultron_app/features/chat/chat_state.dart';

import '../support/fake_backend.dart';

Future<void> sendViaUi(WidgetTester tester, String text) async {
  await tester.enterText(find.byKey(const Key('composer-input')), text);
  await tester.tap(find.byKey(const Key('send-button')));
  await tester.pump();
}

/// Lets the fake stream deliver everything.
Future<void> drain(WidgetTester tester) async {
  for (var i = 0; i < 20; i++) {
    await tester.pump(const Duration(milliseconds: 30));
  }
}

void main() {
  testWidgets('streams a reply with stages and a LOCAL badge', (tester) async {
    final backend = FakeBackend();
    final app = await pumpUltron(tester, backend, signedIn: true);
    expect(find.text('How can I help?'), findsOneWidget);

    await sendViaUi(tester, 'Hello there');
    expect(find.text('Hello there'), findsOneWidget); // shown immediately
    await tester.pump(const Duration(milliseconds: 25));
    expect(find.byKey(const Key('phase-text')), findsOneWidget);
    // Mid-stream: loading-model stage was reported.
    final seen = <ReplyPhase>{};
    for (var i = 0; i < 20; i++) {
      seen.add(app.container.read(chatProvider).phase);
      await tester.pump(const Duration(milliseconds: 20));
    }
    expect(seen, containsAll([ReplyPhase.loadingModel, ReplyPhase.generating]));
    await drain(tester);

    final state = app.container.read(chatProvider);
    expect(state.busy, isFalse);
    final reply = state.messages.last;
    expect(reply.content, 'Hello from ULTRON');
    expect(reply.status, MessageStatus.complete);
    expect(reply.isLocal, isTrue);
    expect(find.text('Hello from ULTRON'), findsOneWidget);
    expect(find.text('LOCAL'), findsWidgets);
    expect(find.text('ollama · qwen3.5:4b'), findsOneWidget);
    // The conversation was created and appears in the list.
    expect(backend.conversations, hasLength(1));
    expect(find.byKey(Key('conversation-${backend.conversations.first['id']}')), findsOneWidget);
    // Header picks up the title the backend gave the conversation.
    expect(
      find.descendant(of: find.byKey(const Key('chat-title')), matching: find.text('Hello there'), matchRoot: true),
      findsOneWidget,
    );
  });

  testWidgets('backend error event is shown with a friendly message', (tester) async {
    final backend = FakeBackend()
      ..replyScript = (_, _) => [
        ('status', {'phase': 'routing'}),
        (
          'error',
          {
            'code': 'private_requires_local_ai',
            'message': 'raw',
            'assistant_message': {
              'id': 'a1',
              'role': 'assistant',
              'content': '',
              'status': 'failed',
              'fallback_used': false,
              'error_code': 'private_requires_local_ai',
              'created_at': '2026-11-09T10:00:00Z',
            },
          },
        ),
      ];
    final app = await pumpUltron(tester, backend, signedIn: true);
    await sendViaUi(tester, 'secret');
    await drain(tester);
    final reply = app.container.read(chatProvider).messages.last;
    expect(reply.status, MessageStatus.failed);
    expect(find.textContaining('can only use local AI'), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
  });

  testWidgets('request rejected before streaming (e.g. busy) is reported', (tester) async {
    final backend = FakeBackend()
      ..messageStatus = 409
      ..messageError = {'code': null, 'message': 'A reply is already being generated'};
    final app = await pumpUltron(tester, backend, signedIn: true);
    await sendViaUi(tester, 'hi');
    await drain(tester);
    final s = app.container.read(chatProvider);
    expect(s.busy, isFalse);
    expect(s.messages.last.status, MessageStatus.failed);
    expect(find.textContaining('already being generated'), findsOneWidget);
  });

  testWidgets('stop button cancels the reply on the server', (tester) async {
    final backend = FakeBackend()..holdReply = Completer<void>();
    final app = await pumpUltron(tester, backend, signedIn: true);
    await sendViaUi(tester, 'long answer please');
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.byKey(const Key('stop-button')), findsOneWidget);
    await tester.tap(find.byKey(const Key('stop-button')));
    await drain(tester);
    expect(backend.cancelCalls, 1);
    final s = app.container.read(chatProvider);
    expect(s.busy, isFalse);
    expect(s.messages.last.status, MessageStatus.cancelled);
    expect(find.text('Stopped'), findsOneWidget);
    expect(find.byKey(const Key('send-button')), findsOneWidget);
  });

  testWidgets('private toggle creates a private conversation', (tester) async {
    final backend = FakeBackend();
    final app = await pumpUltron(tester, backend, signedIn: true);
    await tester.tap(find.byKey(const Key('private-toggle')));
    await tester.pump();
    expect(find.text('Private conversation'), findsOneWidget);
    await sendViaUi(tester, 'my diary');
    await drain(tester);
    expect(backend.bodies['POST /api/v1/conversations'], {'is_private': true});
    expect(app.container.read(chatProvider).conversation!.isPrivate, isTrue);
    // Once started, privacy can't be switched off.
    final chip = tester.widget<FilterChip>(find.byKey(const Key('private-toggle')));
    expect(chip.onSelected, isNull);
  });

  testWidgets('opening a conversation from the list loads its messages', (tester) async {
    final backend = FakeBackend();
    final c = backend.addConversation(title: 'Earlier chat');
    backend.messages[c['id'] as String]!
      ..add(backend.message('user', 'What is 2+2?'))
      ..add(backend.message('assistant', 'It is 4.', kind: 'cloud', provider: 'groq', model: 'llama'));
    await pumpUltron(tester, backend, signedIn: true);
    await tester.tap(find.text('Earlier chat'));
    await drain(tester);
    expect(find.text('It is 4.'), findsOneWidget);
    expect(find.text('CLOUD'), findsWidgets);
    expect(find.byKey(const Key('chat-title')), findsOneWidget);
  });

  testWidgets('Enter sends on desktop', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true);
    await tester.enterText(find.byKey(const Key('composer-input')), 'via enter');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await drain(tester);
    expect(backend.messages.values.first.first['content'], 'via enter');
  });

  testWidgets('phones open the conversation list in a sheet', (tester) async {
    final backend = FakeBackend()..addConversation(title: 'On my phone');
    await pumpUltron(tester, backend, signedIn: true, size: const Size(412, 892));
    expect(find.byKey(const Key('conversation-panel')), findsNothing);
    await tester.tap(find.byKey(const Key('open-conversations')));
    await drain(tester); // sheet animation + list load
    expect(find.text('On my phone'), findsOneWidget);
    await tester.tap(find.text('On my phone'));
    await drain(tester);
    expect(find.byType(BottomSheet), findsNothing); // sheet closed
    expect(find.text('On my phone'), findsOneWidget); // now the chat title
  });
}
