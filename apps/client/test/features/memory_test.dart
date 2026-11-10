import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_backend.dart';
import 'tasks_test.dart' show settle;

const _tall = Size(1280, 1600);

Map<String, dynamic> memory(String id, String content, {bool pinned = false, bool private = false}) => {
  'id': id,
  'content': content,
  'kind': 'fact',
  'source': 'user',
  'is_private': private,
  'pinned': pinned,
  'last_used_at': null,
  'created_at': '2026-11-10T10:00:00Z',
  'updated_at': '2026-11-10T10:00:00Z',
};

Future<void> openMemory(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('nav-memory')));
  await settle(tester);
}

void main() {
  testWidgets('lists, searches, pins and deletes memories', (tester) async {
    final backend = FakeBackend();
    backend.memories.addAll([
      memory('m1', 'Exams start 2 December'),
      memory('m2', 'Allergic to peanuts', private: true),
    ]);
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openMemory(tester);
    expect(find.text('Exams start 2 December'), findsOneWidget);
    expect(find.byIcon(Icons.lock), findsOneWidget);

    await tester.enterText(find.byKey(const Key('memory-search')), 'exam');
    await settle(tester);
    expect(find.text('Allergic to peanuts'), findsNothing);

    await tester.tap(find.byKey(const Key('pin-m1')));
    await settle(tester);
    expect(backend.memories.first['pinned'], isTrue);

    await tester.tap(find.byKey(const Key('delete-memory-m1')));
    await settle(tester);
    expect(find.text('Exams start 2 December'), findsNothing);
  });

  testWidgets('adds a memory through the dialog', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openMemory(tester);
    await tester.tap(find.byKey(const Key('add-memory')));
    await settle(tester);
    await tester.enterText(find.byKey(const Key('memory-text')), 'My locker is number 42');
    await tester.tap(find.byKey(const Key('memory-private')));
    await tester.tap(find.byKey(const Key('memory-save')));
    await settle(tester);
    expect(backend.memories.single['content'], 'My locker is number 42');
    expect(backend.memories.single['is_private'], isTrue);
    expect(find.text('My locker is number 42'), findsOneWidget);
  });

  testWidgets('export copies JSON; delete all asks first', (tester) async {
    final backend = FakeBackend();
    backend.memories.add(memory('m1', 'One thing'));
    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') copied = (call.arguments as Map)['text'] as String;
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openMemory(tester);

    await tester.tap(find.byKey(const Key('memory-menu')));
    await settle(tester);
    await tester.tap(find.text('Export (copy JSON)'));
    await settle(tester);
    expect(copied, contains('One thing'));

    await tester.tap(find.byKey(const Key('memory-menu')));
    await settle(tester);
    await tester.tap(find.text('Delete all…'));
    await settle(tester);
    expect(backend.memories, isNotEmpty); // not until confirmed
    await tester.tap(find.byKey(const Key('confirm-delete-all')));
    await settle(tester);
    expect(backend.memories, isEmpty);
  });

  testWidgets('memory can be switched off for chat', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openMemory(tester);
    await tester.tap(find.byKey(const Key('memory-enabled')));
    await settle(tester);
    expect(backend.preferences['memory_enabled'], isFalse);
  });
}
