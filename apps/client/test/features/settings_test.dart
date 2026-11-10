import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/settings/app_settings.dart';
import 'package:ultron_app/core/theme/ultron_colors.dart';

import '../support/fake_backend.dart';

const _tall = Size(1280, 2400);

Future<void> settle(WidgetTester tester, [int frames = 6]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> openSection(WidgetTester tester, String name) async {
  await tester.tap(find.byKey(Key('nav-$name')));
  await settle(tester);
}

bool chatIsPrivate(WidgetTester tester) => tester.widget<FilterChip>(find.byKey(const Key('private-toggle'))).selected;

void main() {
  testWidgets('loads AI preferences and saves a new routing mode', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openSection(tester, 'settings');

    expect(find.text('AI ROUTING'), findsOneWidget);
    await tester.tap(find.text('Local only'));
    await settle(tester);
    expect(backend.preferenceSaves, 1);
    expect((backend.bodies['PUT /api/v1/ai/preferences']! as Map)['mode'], 'local_only');
    expect(find.textContaining('Nothing goes to the cloud'), findsOneWidget);
  });

  testWidgets('cloud order lists saved order first, then unplaced providers', (tester) async {
    await pumpUltron(tester, FakeBackend(), signedIn: true, size: _tall);
    await openSection(tester, 'settings');

    double y(String name) => tester.getTopLeft(find.byKey(ValueKey('provider-$name'))).dy;
    expect(y('groq'), lessThan(y('gemini')));
    expect(y('gemini'), lessThan(y('openrouter')));
  });

  testWidgets('dragging a provider saves the new order', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openSection(tester, 'settings');

    final handle = find.descendant(
      of: find.byKey(const ValueKey('provider-openrouter')),
      matching: find.byIcon(Icons.drag_indicator),
    );
    final gesture = await tester.startGesture(tester.getCenter(handle));
    await tester.pump(const Duration(milliseconds: 50));
    for (var i = 0; i < 10; i++) {
      await gesture.moveBy(const Offset(0, -15));
      await tester.pump(const Duration(milliseconds: 20));
    }
    await gesture.up();
    await settle(tester);
    expect(backend.preferenceSaves, 1);
    expect((backend.bodies['PUT /api/v1/ai/preferences']! as Map)['cloud_order'], ['openrouter', 'groq', 'gemini']);
  });

  testWidgets('a failed save shows the reason and keeps the old value', (tester) async {
    final backend = FakeBackend();
    backend.routes['PUT /api/v1/ai/preferences'] = (_, _) async =>
        FakeBackend.json(422, {'detail': 'cloud_order must list distinct known cloud providers'});
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openSection(tester, 'settings');

    await tester.tap(find.text('Cloud only'));
    await settle(tester);
    expect(find.text('cloud_order must list distinct known cloud providers'), findsOneWidget);
    expect(find.textContaining('Cloud AI first'), findsOneWidget); // still "auto"
  });

  testWidgets('private by default applies to new chats', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    expect(chatIsPrivate(tester), isFalse);

    await openSection(tester, 'settings');
    await tester.tap(find.byKey(const Key('private-default')));
    await settle(tester);
    expect(backend.preferences['private_by_default'], isTrue);

    await openSection(tester, 'chat');
    expect(chatIsPrivate(tester), isTrue);
  });

  testWidgets('a saved private default applies at sign-in without opening settings', (tester) async {
    final backend = FakeBackend()..preferences['private_by_default'] = true;
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await settle(tester, 3);
    expect(chatIsPrivate(tester), isTrue);

    // "New conversation" keeps following the preference.
    await tester.tap(find.byKey(const Key('private-toggle')));
    await tester.pump();
    expect(chatIsPrivate(tester), isFalse);
    await tester.tap(find.byKey(const Key('new-chat')));
    await tester.pump();
    expect(chatIsPrivate(tester), isTrue);
  });

  testWidgets('accent and motion are saved on the device', (tester) async {
    final app = await pumpUltron(tester, FakeBackend(), signedIn: true, size: _tall);
    await openSection(tester, 'settings');

    await tester.tap(find.byKey(const Key('accent-violet')));
    await tester.tap(find.text('Off'));
    await settle(tester);
    final s = app.container.read(settingsProvider);
    expect(s.accent, UltronAccent.violet);
    expect(s.motion, MotionLevel.off);
    expect(Theme.of(tester.element(find.text('APPEARANCE'))).colorScheme.primary, UltronAccent.violet.color);
  });

  testWidgets('voice settings update speak-replies and speed', (tester) async {
    final app = await pumpUltron(tester, FakeBackend(), signedIn: true, size: _tall);
    await openSection(tester, 'settings');

    await tester.tap(find.byKey(const Key('speak-replies')));
    await tester.pump();
    expect(app.container.read(settingsProvider).speakReplies, isTrue);
  });

  testWidgets('account section shows the device and signs out', (tester) async {
    await pumpUltron(tester, FakeBackend(), signedIn: true, size: _tall);
    await openSection(tester, 'settings');

    expect(find.text(ownerEmail), findsOneWidget);
    expect(find.text('Windows PC (windows)'), findsOneWidget);
    await tester.tap(find.byKey(const Key('sign-out')));
    await settle(tester);
    expect(find.byKey(const Key('sign-in')), findsOneWidget);
  });
}
