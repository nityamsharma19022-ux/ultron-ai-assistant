import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/auth/session.dart';

import '../support/fake_backend.dart';

void main() {
  testWidgets('shows sign-in when there are no saved tokens', (tester) async {
    await pumpUltron(tester, FakeBackend());
    expect(find.byKey(const Key('sign-in')), findsOneWidget);
    expect(find.text('ULTRON'), findsWidgets);
  });

  testWidgets('validates the form before calling the backend', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend);
    await tester.enterText(find.byKey(const Key('backend-url')), 'not a url');
    await tester.tap(find.byKey(const Key('sign-in')));
    await tester.pump();
    expect(find.text('Enter an address like http://127.0.0.1:8000'), findsOneWidget);
    expect(find.text('Enter your email'), findsOneWidget);
    expect(backend.requests, isEmpty);
  });

  testWidgets('test connection shows which backend answered', (tester) async {
    await pumpUltron(tester, FakeBackend());
    await tester.tap(find.byTooltip('Test connection'));
    await tester.pump();
    await tester.pump();
    expect(find.textContaining('Connected to ultron-windows-local'), findsOneWidget);
  });

  testWidgets('wrong password shows an error and stays on sign-in', (tester) async {
    await pumpUltron(tester, FakeBackend());
    await tester.enterText(find.byKey(const Key('email')), ownerEmail);
    await tester.enterText(find.byKey(const Key('password')), 'wrong');
    await tester.tap(find.byKey(const Key('sign-in')));
    await tester.pump();
    await tester.pump();
    expect(find.text('Wrong email or password.'), findsOneWidget);
  });

  testWidgets('successful sign-in opens the main interface', (tester) async {
    final backend = FakeBackend();
    final app = await pumpUltron(tester, backend);
    await tester.enterText(find.byKey(const Key('email')), ownerEmail);
    await tester.enterText(find.byKey(const Key('password')), ownerPassword);
    await tester.tap(find.byKey(const Key('sign-in')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));
    expect(app.container.read(sessionProvider), isA<SignedIn>());
    expect(find.byKey(const Key('sidebar')), findsOneWidget);
    expect(app.tokens.tokens?.accessToken, 'access-1');
  });

  testWidgets('saved tokens restore the session without signing in', (tester) async {
    await pumpUltron(tester, FakeBackend(), signedIn: true);
    expect(find.byKey(const Key('sidebar')), findsOneWidget);
  });

  testWidgets('saved tokens but backend offline shows retry screen', (tester) async {
    final backend = FakeBackend()..online = false;
    await pumpUltron(tester, backend, signedIn: true);
    expect(find.text('RETRY'), findsOneWidget);
    backend.online = true;
    await tester.tap(find.text('RETRY'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.byKey(const Key('sidebar')), findsOneWidget);
  });
}
