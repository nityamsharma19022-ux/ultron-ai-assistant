import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/features/agent/phone_agent.dart';

import '../support/fake_backend.dart';
import '../support/fake_platform.dart';
import 'tasks_test.dart' show settle;

void main() {
  testWidgets('the phone says hello and runs phone steps', (tester) async {
    final backend = FakeBackend();
    backend.pendingSteps.addAll([
      {
        'id': 'p1',
        'task_id': 't',
        'task_title': 'x',
        'tool': 'phone.alarm.set',
        'args': {'hour': 6, 'minute': 30},
        'title': 'Set an alarm',
        'attempt': 1,
      },
      {
        'id': 'p2',
        'task_id': 't',
        'task_title': 'x',
        'tool': 'pc.apps.open',
        'args': {'app': 'x'},
        'title': 'wrong device',
        'attempt': 1,
      },
    ]);
    final phone = FakePhonePlatform();
    final app = await pumpUltron(tester, backend, signedIn: true, phonePlatform: phone);
    await settle(tester, 20);
    expect(backend.agentHelloBody!['tools'], phoneTools);
    expect(backend.agentHelloBody!['capabilities'], {
      'apps': ['Spotify', 'Camera'],
    });
    expect(phone.calls.first.$1, 'setAlarm');
    expect(phone.calls.first.$2, {'hour': 6, 'minute': 30, 'label': 'ULTRON'});
    expect(backend.stepResults['p1']!['ok'], isTrue);
    expect(backend.stepResults['p1']!['result']['summary'], 'setAlarm done');
    expect(backend.stepResults['p2']!['ok'], isFalse);
    expect(app.container.read(phoneAgentProvider).active, isTrue);
  });

  testWidgets('phone errors are reported as failed steps', (tester) async {
    final backend = FakeBackend();
    backend.pendingSteps.add({
      'id': 'p1',
      'task_id': 't',
      'task_title': 'x',
      'tool': 'phone.apps.open',
      'args': {'app': 'Nope'},
      'title': 'Open Nope',
      'attempt': 1,
    });
    final phone = FakePhonePlatform()..reply = (m, a) => {'ok': false, 'error': "No app called 'Nope' on this phone"};
    await pumpUltron(tester, backend, signedIn: true, phonePlatform: phone);
    await settle(tester, 20);
    expect(backend.stepResults['p1'], {
      'ok': false,
      'result': <String, dynamic>{},
      'error': "No app called 'Nope' on this phone",
    });
  });

  testWidgets('due reminders notify and are marked delivered', (tester) async {
    final backend = FakeBackend();
    backend.dueReminders.add({'id': 'r1', 'text': 'Call mom', 'due_at': '2026-11-10T10:00:00Z', 'done': false});
    final phone = FakePhonePlatform();
    await pumpUltron(tester, backend, signedIn: true, phonePlatform: phone);
    await tester.pump(const Duration(seconds: 31));
    await settle(tester);
    expect(phone.calls.where((c) => c.$1 == 'notify').single.$2!['text'], 'Call mom');
    expect(backend.deliveredReminders, ['r1']);
    expect(find.text('⏰ Reminder: Call mom'), findsOneWidget);
  });
}
