import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/time_format.dart';
import 'package:ultron_app/features/shell/sections.dart';

import '../support/fake_backend.dart';
import 'chat_test.dart' show drain, sendViaUi;
import 'tasks_test.dart' show settle;

String clockOnScreen(WidgetTester tester) => tester
    .widget<RichText>(find.descendant(of: find.byKey(const Key('clock-time')), matching: find.byType(RichText)))
    .text
    .toPlainText();

void main() {
  test('12-hour clock: midnight, noon, AM and PM', () {
    expect(clockText(0, 5), '12:05 AM');
    expect(clockText(0, 0), '12:00 AM');
    expect(clockText(9, 30), '9:30 AM');
    expect(clockText(12, 0), '12:00 PM');
    expect(clockText(12, 45), '12:45 PM');
    expect(clockText(18, 15), '6:15 PM');
    expect(clockText(23, 59), '11:59 PM');
    expect(clockText(18, 15, h24: true), '18:15');
    expect(hhmmText('22:00'), '10:00 PM');
    expect(hhmmText('07:00'), '7:00 AM');
    expect(hhmmText('22:00', h24: true), '22:00');
  });

  test('day and time in local time', () {
    final now = DateTime(2026, 11, 10, 21, 0);
    expect(dayTimeText(DateTime(2026, 11, 10, 21, 30), now: now), 'Today 9:30 PM');
    expect(dayTimeText(DateTime(2026, 11, 11, 0, 10), now: now), 'Tomorrow 12:10 AM');
    expect(dayTimeText(DateTime(2026, 11, 9, 12, 0), now: now), 'Yesterday 12:00 PM');
    expect(dayTimeText(DateTime(2026, 11, 14, 18, 15), now: now), '14 Nov 6:15 PM');
    expect(dayTimeText(DateTime(2027, 1, 2, 9, 5), now: now), '2 Jan 2027 9:05 AM');
    // Times stored in UTC are shown in this device's time zone.
    final utc = DateTime.utc(2026, 11, 10, 15, 30);
    final local = utc.toLocal();
    expect(timeText(utc), clockText(local.hour, local.minute));
  });

  testWidgets('Home clock: 12-hour with AM/PM and a greeting with "Sir"', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: const Size(1600, 1400), section: AppSection.home);
    await settle(tester);
    final shown = clockOnScreen(tester);
    expect(shown, matches(RegExp(r'^(1[0-2]|[1-9]):[0-5]\d (AM|PM)$')));
    expect(find.textContaining(', Sir ·'), findsOneWidget);
  });

  testWidgets('24-hour clock and no title when chosen', (tester) async {
    final backend = FakeBackend();
    backend.preferences = {...backend.preferences, 'time_format': '24h', 'address_as': ''};
    await pumpUltron(tester, backend, signedIn: true, size: const Size(1600, 1400), section: AppSection.home);
    await settle(tester);
    expect(clockOnScreen(tester), matches(RegExp(r'^([01]\d|2[0-3]):[0-5]\d$')));
    expect(find.textContaining(', Sir'), findsNothing);
  });

  testWidgets('settings: response speed, clock and form of address are saved on Core', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: const Size(1280, 3200), section: AppSection.settings);
    await settle(tester);
    await tester.tap(find.text('Deep reasoning'));
    await settle(tester);
    expect(backend.preferences['response_mode'], 'deep');
    await tester.tap(find.textContaining('24-hour'));
    await settle(tester);
    expect(backend.preferences['time_format'], '24h');
    await tester.enterText(find.byKey(const Key('address-as')), 'Boss');
    await tester.tap(find.byKey(const Key('save-address')));
    await settle(tester);
    expect(backend.preferences['address_as'], 'Boss');
  });

  testWidgets('chat sends the local UTC offset and shows reply timing', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true);
    await sendViaUi(tester, 'Hello');
    await drain(tester);
    final sent = backend.bodies.entries.firstWhere((e) => e.key.endsWith('/messages')).value! as Map;
    expect(sent['utc_offset_minutes'], DateTime.now().timeZoneOffset.inMinutes);
    expect(find.text('0.9 s → 2.4 s'), findsOneWidget);
  });
}
