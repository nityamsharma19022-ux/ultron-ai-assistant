import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/status/system_status.dart';

import '../support/fake_backend.dart';

void main() {
  testWidgets('wide screens get the sidebar', (tester) async {
    await pumpUltron(tester, FakeBackend(), signedIn: true, size: const Size(1280, 800));
    expect(find.byKey(const Key('sidebar')), findsOneWidget);
    expect(find.byKey(const Key('bottom-nav')), findsNothing);
  });

  testWidgets('phones get bottom navigation', (tester) async {
    await pumpUltron(tester, FakeBackend(), signedIn: true, size: const Size(412, 892));
    expect(find.byKey(const Key('bottom-nav')), findsOneWidget);
    expect(find.byKey(const Key('sidebar')), findsNothing);
    // Phones still see the cloud/local indicator, in the top bar.
    expect(find.descendant(of: find.byKey(const Key('top-bar')), matching: find.text('LOCAL')), findsOneWidget);
  });

  testWidgets('navigation switches sections', (tester) async {
    await pumpUltron(tester, FakeBackend(), signedIn: true);
    await tester.tap(find.byKey(const Key('nav-dashboard')));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('SYSTEM STATUS'), findsOneWidget);
  });

  testWidgets('connection indicator shows cloud and local availability', (tester) async {
    await pumpUltron(tester, FakeBackend(), signedIn: true);
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Core online'), findsOneWidget);
    expect(find.text('CLOUD'), findsOneWidget);
    expect(find.text('LOCAL'), findsOneWidget);
  });

  testWidgets('offline banner appears when the backend goes away', (tester) async {
    final backend = FakeBackend();
    final app = await pumpUltron(tester, backend, signedIn: true);
    backend.online = false;
    await app.container.read(systemStatusProvider.notifier).refresh();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byKey(const Key('offline-banner')), findsOneWidget);
    expect(find.text('Core offline'), findsOneWidget);
  });
}
