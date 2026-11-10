import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/features/documents/documents.dart';

import '../support/fake_backend.dart';
import 'chat_test.dart' show drain, sendViaUi;
import 'tasks_test.dart' show settle;

class FakeFiles implements FileSource {
  PickedFile? next = const PickedFile('syllabus.pdf', [37, 80, 68, 70]);
  @override
  Future<PickedFile?> pick() async => next;
}

Future<void> openDocuments(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('nav-memory')));
  await settle(tester);
  await tester.tap(find.byKey(const Key('tab-documents')));
  await settle(tester);
}

void main() {
  testWidgets('upload, ask about it in chat, and the message carries the document', (tester) async {
    final backend = FakeBackend();
    final files = FakeFiles();
    await pumpUltron(tester, backend, signedIn: true, size: const Size(1280, 1000), fileSource: files);
    await openDocuments(tester);
    expect(find.text('No documents yet.'), findsOneWidget);

    await tester.tap(find.byKey(const Key('upload-document')));
    await settle(tester);
    expect(backend.uploads, ['syllabus.pdf']);
    expect(find.text('syllabus.pdf'), findsOneWidget);
    expect(find.textContaining('3 pages'), findsOneWidget);

    await tester.tap(find.byKey(const Key('ask-doc-1')));
    await settle(tester);
    expect(find.byKey(const Key('attached-doc-1')), findsOneWidget);
    await tester.pump(const Duration(seconds: 5)); // let the "Added …" snack bar go
    await settle(tester);
    await sendViaUi(tester, 'What does unit 4 cover?');
    await drain(tester);
    final sent = backend.bodies.entries.firstWhere((e) => e.key.endsWith('/messages')).value as Map;
    expect(sent['document_ids'], ['doc-1']);

    // Removing the chip stops sending it.
    await tester.tap(find.descendant(of: find.byKey(const Key('attached-doc-1')), matching: find.byIcon(Icons.clear)));
    await settle(tester);
    expect(find.byKey(const Key('attachments-bar')), findsNothing);
  });

  testWidgets('attach from the chat box', (tester) async {
    final backend = FakeBackend();
    backend.documents.add({
      'id': 'doc-9',
      'name': 'notes.md',
      'kind': 'text',
      'size': 100,
      'pages': null,
      'chars': 100,
      'chunk_count': 1,
      'is_private': false,
      'source': 'upload',
      'created_at': '2026-11-10T10:00:00Z',
    });
    await pumpUltron(tester, backend, signedIn: true, fileSource: FakeFiles());
    await tester.tap(find.byKey(const Key('attach-button')));
    await settle(tester);
    expect(find.byKey(const Key('attach-sheet')), findsOneWidget);
    await tester.tap(find.byKey(const Key('attach-doc-9')));
    await settle(tester);
    expect(find.byKey(const Key('attached-doc-9')), findsOneWidget);
  });

  testWidgets('deleting a document', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: const Size(1280, 1000), fileSource: FakeFiles());
    await openDocuments(tester);
    await tester.tap(find.byKey(const Key('upload-document')));
    await settle(tester);
    await tester.tap(find.byKey(const Key('delete-document-doc-1')));
    await settle(tester);
    expect(backend.documents, isEmpty);
    expect(find.text('syllabus.pdf'), findsNothing);
  });
}
