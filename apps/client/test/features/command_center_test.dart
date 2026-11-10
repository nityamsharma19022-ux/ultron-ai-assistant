import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/settings/app_settings.dart';
import 'package:ultron_app/features/command/command_controller.dart';
import 'package:ultron_app/features/shell/sections.dart';
import 'package:ultron_app/features/tasks/tasks_controller.dart';

import '../support/fake_backend.dart';

const _big = Size(1600, 1400);

Future<void> settle(WidgetTester tester, [int frames = 8]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

FakeBackend _backend() {
  final b = FakeBackend();
  b.metrics.addAll([
    {
      'device_id': 'device-1',
      'device_name': 'Windows PC',
      'platform': 'windows',
      'metrics': {'cpu_percent': 37.0, 'memory_percent': 92.0, 'disk_free_gb': 120.0},
      'updated_at': DateTime.now().toUtc().toIso8601String(),
    },
    {
      'device_id': 'device-2',
      'device_name': 'Pixel phone',
      'platform': 'android',
      'metrics': {'battery_percent': 12, 'charging': false, 'network': 'wifi'},
      'updated_at': DateTime.now().toUtc().toIso8601String(),
    },
  ]);
  b.notifications.addAll([
    b.notification('n1', 'Task failed: Organize downloads', priority: 'high'),
    b.notification('n2', 'Good morning', read: true),
  ]);
  b.tasks.add(
    b.task('t1', 'Open VS Code', 'awaiting_approval', [FakeBackend.step('s1', 'Open VS Code', 'awaiting_approval')]),
  );
  b.upcomingReminders.add({
    'id': 'r1',
    'text': 'Stretch',
    'due_at': DateTime.now().add(const Duration(hours: 2)).toUtc().toIso8601String(),
    'done': false,
    'delivered_at': null,
    'task_id': null,
  });
  return b;
}

void main() {
  testWidgets('Home is the Command Center: clock, devices, tasks, reminders, notifications', (tester) async {
    final backend = _backend();
    await pumpUltron(tester, backend, signedIn: true, size: _big, section: AppSection.home);
    await settle(tester);

    expect(find.byKey(const Key('command-clock')), findsOneWidget);
    expect(find.byKey(const Key('panel-devices')), findsOneWidget);
    expect(find.text('Windows PC'), findsWidgets);
    expect(find.text('37%'), findsOneWidget);
    expect(find.text('92%'), findsOneWidget); // memory: shown in red
    expect(find.text('12%'), findsOneWidget); // phone battery
    expect(find.textContaining('Network: wifi'), findsOneWidget);
    expect(find.text('Need approval'), findsOneWidget);
    expect(find.text('Stretch'), findsOneWidget);
    expect(find.text('Task failed: Organize downloads'), findsWidgets);
    expect(find.text('Normal'), findsWidgets); // chip shows the active mode's name
  });

  testWidgets('the app starts on Home', (tester) async {
    final app = await pumpUltron(tester, _backend(), signedIn: true, size: _big, section: AppSection.home);
    await settle(tester);
    expect(app.container.read(sectionProvider), AppSection.home);
    // Default for a fresh app (pumpUltron otherwise selects Chat for older tests).
    final fresh = ProviderContainer();
    addTearDown(fresh.dispose);
    expect(fresh.read(sectionProvider), AppSection.home);
  });

  testWidgets('quick commands go to ULTRON', (tester) async {
    final backend = _backend();
    await pumpUltron(tester, backend, signedIn: true, size: _big, section: AppSection.home);
    await settle(tester);
    await tester.tap(find.byKey(const Key('quick-how-is-my-pc-doing')));
    await settle(tester);
    expect(backend.commands, ['How is my PC doing']);
    expect(find.text('You said: How is my PC doing'), findsOneWidget); // shown as a message
  });

  testWidgets('switching the operating mode', (tester) async {
    final backend = _backend();
    await pumpUltron(tester, backend, signedIn: true, size: _big, section: AppSection.home);
    await settle(tester);
    await tester.tap(find.byKey(const Key('mode-chip')));
    await settle(tester);
    await tester.tap(find.byKey(const Key('mode-focus')).last);
    await settle(tester);
    expect(backend.activeMode, 'focus');
    expect(find.text('Focus'), findsWidgets);
  });

  testWidgets('autonomy level per area', (tester) async {
    final backend = _backend();
    await pumpUltron(tester, backend, signedIn: true, size: _big, section: AppSection.home);
    await settle(tester);
    final slider = find.byKey(const Key('level-pc'));
    await tester.ensureVisible(slider);
    await settle(tester, 2);
    // Drag to the far right: level 5.
    await tester.drag(slider, const Offset(600, 0));
    await settle(tester);
    expect(backend.levels['pc'], 5);
    expect(find.text('5 · Complex workflows'), findsOneWidget);
    expect(backend.levels['core'], 3);
  });

  testWidgets('bell shows unread notifications; mark all read', (tester) async {
    final backend = _backend();
    await pumpUltron(tester, backend, signedIn: true, size: _big);
    await settle(tester);
    expect(find.byKey(const Key('unread-count')), findsOneWidget);
    expect(find.text('1'), findsWidgets);
    await tester.tap(find.byKey(const Key('notification-bell')));
    await settle(tester);
    expect(find.byKey(const Key('notifications-sheet')), findsOneWidget);
    await tester.tap(find.byKey(const Key('read-all')));
    await settle(tester);
    expect(backend.notifications.every((n) => n['read'] == true), isTrue);
    final badge = tester.widget<Badge>(
      find.descendant(of: find.byKey(const Key('notification-bell')), matching: find.byType(Badge)),
    );
    expect(badge.isLabelVisible, isFalse);
  });

  testWidgets('new important notifications pop up', (tester) async {
    final old = NotificationsController.pollEvery;
    NotificationsController.pollEvery = const Duration(seconds: 1);
    addTearDown(() => NotificationsController.pollEvery = old);
    final backend = _backend();
    await pumpUltron(tester, backend, signedIn: true, size: _big);
    await settle(tester);
    backend.notifications.insert(0, backend.notification('n3', 'Battery low on Pixel phone', priority: 'high'));
    backend.notifications.insert(0, backend.notification('n4', 'Something minor', priority: 'low'));
    await tester.pump(const Duration(seconds: 1));
    await settle(tester);
    expect(find.text('🔔 Battery low on Pixel phone'), findsOneWidget);
    expect(find.text('🔔 Something minor'), findsNothing); // not announced
  });

  testWidgets('floating panels can be dragged and remember their place', (tester) async {
    final app = await pumpUltron(tester, _backend(), signedIn: true, size: _big, section: AppSection.home);
    await settle(tester);
    await tester.tap(find.byIcon(Icons.picture_in_picture_alt_outlined));
    await settle(tester);
    final prefs = app.container.read(sharedPreferencesProvider);
    expect(prefs.getString('command_layout'), 'floating');
    final before = tester.getTopLeft(find.byKey(const Key('panel-tasks')));
    await tester.drag(find.byKey(const Key('drag-tasks')), const Offset(120, 60));
    await settle(tester);
    final after = tester.getTopLeft(find.byKey(const Key('panel-tasks')));
    // Pan gestures start after a small slop, so the move is a bit shorter.
    expect(after.dx, greaterThan(before.dx + 60));
    expect(after.dy, greaterThan(before.dy + 20));
    expect(prefs.getString('command_panel_tasks'), isNotNull);
    await tester.tap(find.byKey(const Key('reset-panels')));
    await settle(tester);
    expect(prefs.getString('command_panel_tasks'), isNull);
  });

  testWidgets('phone layout shows the Command Center in one column', (tester) async {
    await pumpUltron(tester, _backend(), signedIn: true, size: const Size(412, 900), section: AppSection.home);
    await settle(tester);
    expect(find.byKey(const Key('command-center')), findsOneWidget);
    expect(find.byKey(const Key('command-layout')), findsNothing); // floating is desktop-only
    expect(tester.takeException(), isNull);
  });

  testWidgets('search finds words across all conversations', (tester) async {
    final backend = _backend();
    final c = backend.addConversation(title: 'Physics');
    backend.searchHits.add({
      'conversation_id': c['id'],
      'conversation_title': 'Physics',
      'is_private': false,
      'project': 'Exams',
      'message_id': 'm1',
      'role': 'user',
      'snippet': 'Explain the «thermodynamics» exam topics',
      'created_at': '2026-11-10T10:00:00Z',
    });
    await pumpUltron(tester, backend, signedIn: true, size: _big);
    await settle(tester);
    await tester.enterText(find.byKey(const Key('conversation-search')), 'thermodynamics');
    await tester.pump(const Duration(milliseconds: 400));
    await settle(tester);
    expect(find.byKey(const Key('search-results')), findsOneWidget);
    expect(find.byKey(const Key('hit-m1')), findsOneWidget);
    await tester.tap(find.byKey(const Key('hit-m1')));
    await settle(tester);
    expect(backend.requests.any((r) => r.url.path == '/api/v1/conversations/${c['id']}'), isTrue);

    await tester.enterText(find.byKey(const Key('conversation-search')), 'zebra');
    await tester.pump(const Duration(milliseconds: 400));
    await settle(tester);
    expect(find.text('Nothing found'), findsOneWidget);
  });

  testWidgets('settings: custom mode, quiet hours, background and data export', (tester) async {
    final backend = _backend();
    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') copied = (call.arguments as Map)['text'] as String;
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));
    final app = await pumpUltron(
      tester,
      backend,
      signedIn: true,
      size: const Size(1280, 3200),
      section: AppSection.settings,
    );
    await settle(tester);

    await tester.tap(find.byKey(const Key('add-mode')));
    await settle(tester);
    await tester.enterText(find.byKey(const Key('mode-name')), 'Exam week');
    await tester.tap(find.byKey(const Key('mode-save')));
    await settle(tester);
    expect(backend.customModes.single['name'], 'Exam week');
    expect(find.byKey(const Key('mode-option-exam-week')), findsOneWidget);
    await tester.tap(find.byKey(const Key('mode-option-work')));
    await settle(tester);
    expect(backend.activeMode, 'work');

    await tester.tap(find.byKey(const Key('quiet-hours')));
    await settle(tester);
    expect(backend.notificationSettings['quiet_start'], '22:00');
    expect(backend.notificationSettings['quiet_end'], '07:00');
    expect(find.text('10:00 PM – 7:00 AM'), findsOneWidget); // 12-hour by default

    await tester.tap(find.byKey(const Key('preset-nebula')));
    await settle(tester);
    final s = app.container.read(settingsProvider);
    expect(s.accent.name, 'violet');
    expect(s.background, BackgroundStyle.aurora);
    expect(find.byKey(const Key('background-aurora')), findsOneWidget);

    await tester.tap(find.byKey(const Key('export-all')));
    await settle(tester);
    expect(backend.exports, 1);
    expect(copied, contains('ultron-export/1'));
  });

  testWidgets('AI activity refreshes by itself', (tester) async {
    final old = ActivityController.pollEvery;
    ActivityController.pollEvery = const Duration(seconds: 1);
    addTearDown(() => ActivityController.pollEvery = old);
    final backend = _backend();
    await pumpUltron(tester, backend, signedIn: true, size: _big, section: AppSection.home);
    await settle(tester);
    expect(find.text('No activity yet.'), findsOneWidget);
    backend.activity.add({
      'seq': 1,
      'kind': 'task.failed',
      'summary': 'Failed: Open files',
      'task_id': null,
      'created_at': DateTime.now().toUtc().toIso8601String(),
    });
    await tester.pump(const Duration(seconds: 1));
    await settle(tester);
    expect(find.text('Failed: Open files'), findsOneWidget);
  });
}
