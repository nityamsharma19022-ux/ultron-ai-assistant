import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/net/fingerprint.dart';
import 'package:ultron_app/core/settings/app_settings.dart';

import '../support/fake_backend.dart';
import 'tasks_test.dart' show settle;

final _fp = 'a7f2987ac1e74779180f4526b009ea7eb91dd13acc2d45b72053ac861d3efcd8';

Future<void> fillPairing(WidgetTester tester, String url, String code) async {
  await tester.tap(find.byKey(const Key('use-pairing')));
  await settle(tester, 3);
  await tester.enterText(find.byKey(const Key('backend-url')), url);
  await tester.enterText(find.byKey(const Key('pairing-code')), code);
  await tester.enterText(find.byKey(const Key('device-name')), 'iQOO');
  await tester.tap(find.byKey(const Key('sign-in')));
  await settle(tester);
}

void main() {
  test('short fingerprint matches the server format', () {
    expect(shortFingerprint(_fp), 'A7F2-987A … 1D3E-FCD8');
  });

  testWidgets('the PC shows a pairing code with its security code', (tester) async {
    final backend = FakeBackend()..pairingFingerprint = _fp;
    await pumpUltron(tester, backend, signedIn: true, size: const Size(1600, 1400));
    await tester.tap(find.byKey(const Key('nav-dashboard')));
    await settle(tester);
    await tester.tap(find.byKey(const Key('pair-device')));
    await settle(tester);
    expect(find.text('ABCD-EFGH'), findsOneWidget);
    expect(find.text('AAAA-AAAA … BBBB-BBBB'), findsOneWidget);
  });

  testWidgets('pairing over http with a code (no password)', (tester) async {
    final backend = FakeBackend();
    final app = await pumpUltron(tester, backend);
    await fillPairing(tester, 'http://192.168.1.20:8000', 'abcd efgh');
    expect(find.byKey(const Key('sidebar')), findsOneWidget); // signed in
    expect(backend.pairingRedeemBody, {'code': 'abcd efgh', 'device_name': 'iQOO', 'platform': 'android'});
    expect(app.container.read(settingsProvider).backendUrl, 'http://192.168.1.20:8000');
    expect(app.container.read(settingsProvider).tlsFingerprint, isNull);
  });

  testWidgets('a wrong code is refused', (tester) async {
    await pumpUltron(tester, FakeBackend());
    await fillPairing(tester, 'http://192.168.1.20:8000', 'WXYZ-1234');
    expect(find.text('That code is wrong or has expired.'), findsOneWidget);
  });

  testWidgets('over https the user confirms the fingerprint, which is then pinned', (tester) async {
    final backend = FakeBackend()..pairingFingerprint = _fp;
    final app = await pumpUltron(
      tester,
      backend,
      overrides: [
        fingerprintProbeProvider.overrideWithValue((_) async => _fp),
        pinnedClientFactoryProvider.overrideWithValue((_) => backend.client),
      ],
    );
    await fillPairing(tester, 'https://192.168.1.20:8443', 'ABCD-EFGH');
    expect(find.text('A7F2-987A … 1D3E-FCD8'), findsOneWidget);
    await tester.tap(find.byKey(const Key('confirm-fingerprint')));
    await settle(tester);
    expect(app.container.read(settingsProvider).tlsFingerprint, _fp);
    expect(find.byKey(const Key('sidebar')), findsOneWidget);
  });

  testWidgets('cancelling the fingerprint check stops pairing', (tester) async {
    final backend = FakeBackend()..pairingFingerprint = _fp;
    final app = await pumpUltron(
      tester,
      backend,
      overrides: [
        fingerprintProbeProvider.overrideWithValue((_) async => _fp),
        pinnedClientFactoryProvider.overrideWithValue((_) => backend.client),
      ],
    );
    await fillPairing(tester, 'https://192.168.1.20:8443', 'ABCD-EFGH');
    await tester.tap(find.text('Cancel'));
    await settle(tester);
    expect(app.container.read(settingsProvider).tlsFingerprint, isNull);
    expect(backend.pairingRedeemBody, isNull); // the code was never sent
  });

  testWidgets('a certificate that differs from what Core reports stops pairing', (tester) async {
    final backend = FakeBackend()..pairingFingerprint = _fp;
    await pumpUltron(
      tester,
      backend,
      overrides: [
        fingerprintProbeProvider.overrideWithValue((_) async => 'f' * 64), // an interceptor's cert
        pinnedClientFactoryProvider.overrideWithValue((_) => backend.client),
      ],
    );
    await fillPairing(tester, 'https://192.168.1.20:8443', 'ABCD-EFGH');
    expect(find.textContaining('intercepting'), findsOneWidget);
    expect(find.byKey(const Key('confirm-fingerprint')), findsNothing);
    expect(backend.pairingRedeemBody, isNull);
  });
}
