import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_backend.dart';

const _tall = Size(1280, 1600);

Future<void> settle(WidgetTester tester, [int frames = 6]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> openTasks(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('nav-tasks')));
  await settle(tester);
}

void main() {
  testWidgets('the command bar runs a command and shows the task', (tester) async {
    final backend = FakeBackend();
    backend.commandReply = (text) => {
      'type': 'task',
      'message': 'Done. Opened VS Code.',
      'task': backend.task('t1', 'Open VS Code on your PC', 'completed', [
        FakeBackend.step('s1', 'Open VS Code on your PC', 'succeeded', result: {'summary': 'Opened VS Code'}),
      ]),
    };
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openTasks(tester);
    expect(find.textContaining('No tasks yet'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('command-input')), 'open VS Code');
    await tester.tap(find.byKey(const Key('command-send')));
    await settle(tester);
    expect(backend.commands, ['open VS Code']);
    expect(find.text('Done. Opened VS Code.'), findsOneWidget);
    expect(find.byKey(const Key('task-t1')), findsOneWidget);
    expect(find.text('Opened VS Code'), findsOneWidget);
    expect(find.byKey(const Key('repeat-t1')), findsOneWidget);
  });

  testWidgets('questions are answered in place', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openTasks(tester);
    await tester.enterText(find.byKey(const Key('command-input')), 'what time is it in Tokyo');
    await tester.testTextInput.receiveAction(TextInputAction.send);
    await settle(tester);
    expect(find.text('You said: what time is it in Tokyo'), findsOneWidget);
  });

  testWidgets('approval: approve, always allow, reject', (tester) async {
    final backend = FakeBackend();
    backend.tasks.addAll([
      backend.task('a', 'Organize downloads', 'awaiting_approval', [
        FakeBackend.step('sa', 'Organize downloads by type', 'awaiting_approval'),
      ]),
      backend.task('b', 'Delete old.zip', 'awaiting_approval', [
        FakeBackend.step('sb', 'Move downloads/old.zip to the Recycle Bin', 'awaiting_approval', risk: 'B'),
      ]),
    ]);
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openTasks(tester);
    expect(find.text('Needs approval'), findsNWidgets(2));
    expect(find.byKey(const Key('always-a')), findsOneWidget);
    expect(find.byKey(const Key('always-b')), findsNothing); // important changes always ask
    expect(find.text('Important change: always asks'), findsOneWidget);

    await tester.tap(find.byKey(const Key('always-a')));
    await settle(tester);
    expect(find.byKey(const Key('task-status-a')), findsOneWidget);
    expect(tester.widget<Text>(find.byKey(const Key('task-status-a'))).data, 'Done');
    expect(backend.grants, contains('pc.apps'));

    await tester.tap(find.byKey(const Key('reject-b')));
    await settle(tester);
    expect(tester.widget<Text>(find.byKey(const Key('task-status-b'))).data, 'Cancelled');
    expect(find.byKey(const Key('retry-b')), findsOneWidget);
  });

  testWidgets('emergency stop cancels and can be cleared', (tester) async {
    final backend = FakeBackend();
    backend.tasks.add(
      backend.task('r', 'Run tests', 'running', [FakeBackend.step('sr', 'Run the tests workflow', 'running')]),
    );
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openTasks(tester);
    expect(find.byKey(const Key('pause-r')), findsOneWidget);
    await tester.tap(find.byKey(const Key('emergency-stop')));
    await settle(tester);
    expect(backend.automationStopped, isTrue);
    expect(find.text('Emergency stop is on'), findsOneWidget);
    expect(tester.widget<Text>(find.byKey(const Key('task-status-r'))).data, 'Cancelled');
    await tester.tap(find.byKey(const Key('clear-stop')));
    await settle(tester);
    expect(find.text('Automation on'), findsOneWidget);
  });

  testWidgets('permissions tab toggles scopes and the master switch', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openTasks(tester);
    await tester.tap(find.byKey(const Key('tab-permissions')));
    await settle(tester);
    expect(find.text('YOUR PC'), findsOneWidget);
    await tester.tap(find.byKey(const Key('perm-pc.files.organize')));
    await settle(tester);
    expect(backend.grants, contains('pc.files.organize'));
    final delete = tester.widget<SwitchListTile>(find.byKey(const Key('perm-pc.files.delete')));
    expect(delete.onChanged, isNull); // always asks: can't be pre-approved
    await tester.tap(find.byKey(const Key('automation-switch')));
    await settle(tester);
    expect(backend.automationEnabled, isFalse);
  });

  testWidgets('activity tab lists events', (tester) async {
    final backend = FakeBackend();
    backend.activity.addAll([
      {
        'id': '1',
        'seq': 2,
        'kind': 'task.completed',
        'summary': 'Completed: Open VS Code',
        'detail': {},
        'device_id': null,
        'task_id': 't',
        'created_at': '2026-11-10T10:01:00Z',
      },
      {
        'id': '2',
        'seq': 1,
        'kind': 'automation.emergency_stop',
        'summary': 'Emergency stop',
        'detail': {},
        'device_id': null,
        'task_id': null,
        'created_at': '2026-11-10T10:00:00Z',
      },
    ]);
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openTasks(tester);
    await tester.tap(find.byKey(const Key('tab-activity')));
    await settle(tester);
    expect(find.text('Completed: Open VS Code'), findsOneWidget);
    expect(find.text('Emergency stop'), findsOneWidget);
  });
}
