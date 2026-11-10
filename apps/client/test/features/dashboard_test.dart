import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_backend.dart';

const _tall = Size(1600, 1400);

Future<void> openDashboard(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('nav-dashboard')));
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  testWidgets('shows Core, AI sources, local model and devices', (tester) async {
    await pumpUltron(tester, FakeBackend(), signedIn: true, size: _tall);
    await openDashboard(tester);

    expect(find.text('SYSTEM STATUS'), findsOneWidget);
    expect(find.descendant(of: find.byKey(const Key('core-card')), matching: find.text('Online')), findsOneWidget);
    expect(find.text('ultron-windows-local'), findsOneWidget);
    expect(find.text('mode: auto'), findsOneWidget);
    expect(find.text('Loaded (fast replies)'), findsOneWidget);
    expect(find.text('Windows PC (this device)'), findsOneWidget);
    expect(find.text('Pixel phone'), findsOneWidget);
    // The current device can't be signed out from here; others can.
    expect(find.byKey(const Key('revoke-device-1')), findsNothing);
    expect(find.byKey(const Key('revoke-device-2')), findsOneWidget);
  });

  testWidgets('warm-up loads the local model and reports the time', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openDashboard(tester);

    await tester.tap(find.byKey(const Key('warmup-button')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Loaded in 2.5 s'), findsOneWidget);
    expect(backend.requests.where((r) => r.url.path == '/api/v1/ai/local/warmup'), hasLength(1));
  });

  testWidgets('warm-up failure shows the server message', (tester) async {
    final backend = FakeBackend()
      ..warmupStatus = 409
      ..warmupBody = {'detail': 'Local AI is not set up: model not installed'};
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openDashboard(tester);

    await tester.tap(find.byKey(const Key('warmup-button')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Local AI is not set up: model not installed'), findsOneWidget);
  });

  testWidgets('warm-up is disabled when the local model is unavailable', (tester) async {
    final backend = FakeBackend();
    backend.routes['GET /api/v1/ai/status'] = (_, _) async => FakeBackend.json(200, FakeBackend.aiStatus(local: false));
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openDashboard(tester);

    final button = tester.widget<ButtonStyleButton>(find.byKey(const Key('warmup-button')));
    expect(button.onPressed, isNull);
    expect(find.text('Not loaded (first reply will be slower)'), findsOneWidget);
  });

  testWidgets('shows whether the local model runs on the GPU or the CPU', (tester) async {
    final backend = FakeBackend();
    backend.routes['GET /api/v1/ai/status'] = (_, _) async =>
        FakeBackend.json(200, FakeBackend.aiStatus(processor: 'cpu'));
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openDashboard(tester);
    expect(find.text('Processor (CPU), slower'), findsOneWidget);
    expect(find.text('Graphics card (GPU)'), findsNothing);
  });

  testWidgets('signing out another device asks first, then removes it', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true, size: _tall);
    await openDashboard(tester);

    await tester.tap(find.byKey(const Key('revoke-device-2')));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('Sign out this device?'), findsOneWidget);
    await tester.tap(find.byKey(const Key('confirm-revoke')));
    for (var i = 0; i < 5; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(backend.devices[1]['revoked_at'], isNotNull);
    expect(find.text('Pixel phone'), findsNothing);
  });

  testWidgets('Test button checks a provider through Core; usage per model', (tester) async {
    final backend = FakeBackend();
    backend.usageRows.add({
      'provider': 'freellmapi',
      'kind': 'cloud',
      'model': 'groq/llama-3.3-70b',
      'replies': 12,
      'failed': 1,
      'fallbacks': 0,
      'input_tokens': 900,
      'output_tokens': 300,
    });
    await pumpUltron(tester, backend, signedIn: true, size: const Size(1600, 2000));
    await openDashboard(tester);

    await tester.ensureVisible(find.byKey(const Key('test-groq')));
    await tester.tap(find.byKey(const Key('test-groq')));
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(backend.providerTests, ['groq']);
    expect(find.textContaining('Answered "ready" in 0.4s via llama'), findsOneWidget);

    await tester.tap(find.byKey(const Key('test-ollama')));
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(find.text('✗ cannot reach provider'), findsOneWidget);

    await tester.ensureVisible(find.byKey(const Key('usage-card')));
    expect(find.text('FreeLLMAPI'), findsOneWidget);
    expect(find.text('12 replies · 1 failed'), findsOneWidget);
    expect(find.text('groq/llama-3.3-70b · 1200 tokens'), findsOneWidget);
  });
}
