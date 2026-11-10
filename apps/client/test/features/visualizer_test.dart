import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/settings/app_settings.dart';
import 'package:ultron_app/core/status/system_status.dart';
import 'package:ultron_app/core/theme/ultron_colors.dart';
import 'package:ultron_app/features/chat/chat_state.dart';
import 'package:ultron_app/features/visualizer/ai_visualizer.dart';
import 'package:ultron_app/features/visualizer/chat_visualizer.dart';
import 'package:ultron_app/features/visualizer/visualizer_mode.dart';

import '../support/fake_backend.dart';
import 'chat_test.dart' show sendViaUi;

Widget host(Widget child) => MaterialApp(home: Scaffold(body: Center(child: child)));

void main() {
  group('mode selection', () {
    VisualizerMode mode(ReplyPhase p, {BackendLink link = BackendLink.online, bool l = false, bool s = false}) =>
        visualizerModeFor(phase: p, link: link, listening: l, speaking: s);

    test('follows the reply phase', () {
      expect(mode(ReplyPhase.idle), VisualizerMode.idle);
      expect(mode(ReplyPhase.routing), VisualizerMode.thinking);
      expect(mode(ReplyPhase.waiting), VisualizerMode.thinking);
      expect(mode(ReplyPhase.loadingModel), VisualizerMode.loadingModel);
      expect(mode(ReplyPhase.generating), VisualizerMode.generating);
    });

    test('voice and connection states', () {
      expect(mode(ReplyPhase.idle, l: true), VisualizerMode.listening);
      expect(mode(ReplyPhase.generating, l: true), VisualizerMode.listening);
      expect(mode(ReplyPhase.idle, s: true), VisualizerMode.speaking);
      expect(mode(ReplyPhase.generating, s: true), VisualizerMode.generating);
      expect(mode(ReplyPhase.idle, link: BackendLink.offline), VisualizerMode.offline);
      expect(mode(ReplyPhase.generating, link: BackendLink.offline), VisualizerMode.generating);
    });

    test('colour shows where the answer comes from', () {
      const accent = Color(0xFF22D3EE);
      expect(visualizerColor(VisualizerMode.generating, accent, aiKind: 'local'), UltronColors.local);
      expect(visualizerColor(VisualizerMode.generating, accent, aiKind: 'cloud'), UltronColors.cloud);
      expect(visualizerColor(VisualizerMode.loadingModel, accent, aiKind: 'local'), UltronColors.local);
      expect(visualizerColor(VisualizerMode.idle, accent, aiKind: 'local'), accent);
      expect(visualizerColor(VisualizerMode.offline, accent), UltronColors.textMuted);
    });
  });

  testWidgets('paints every mode at large and small sizes without errors', (tester) async {
    for (final size in [280.0, 34.0]) {
      for (final mode in VisualizerMode.values) {
        await tester.pumpWidget(host(AiVisualizer(mode: mode, color: Colors.cyan, size: size, level: 0.6)));
        await tester.pump(const Duration(milliseconds: 50));
        await tester.pump(const Duration(milliseconds: 500));
        expect(tester.takeException(), isNull, reason: '$mode at $size');
        expect(find.bySemanticsLabel('ULTRON status: ${mode.label}'), findsOneWidget);
      }
    }
  });

  testWidgets('eases smoothly from one mode to the next', (tester) async {
    await tester.pumpWidget(host(const AiVisualizer(mode: VisualizerMode.idle, color: Colors.cyan)));
    await tester.pump(const Duration(seconds: 1));
    final state = tester.state<AiVisualizerState>(find.byType(AiVisualizer));
    final idleEnergy = state.currentStyle.energy;
    await tester.pumpWidget(host(const AiVisualizer(mode: VisualizerMode.generating, color: Colors.cyan)));
    await tester.pump(const Duration(milliseconds: 16));
    await tester.pump(const Duration(milliseconds: 16));
    final early = state.currentStyle.energy;
    expect(early, greaterThan(idleEnergy));
    expect(early, lessThan(VisualizerStyle.of(VisualizerMode.generating).energy)); // not a jump
    for (var i = 0; i < 120; i++) {
      await tester.pump(const Duration(milliseconds: 16));
    }
    expect(state.currentStyle.energy, closeTo(VisualizerStyle.of(VisualizerMode.generating).energy, 0.02));
  });

  testWidgets('motion Off shows a still image with no animation running', (tester) async {
    await tester.pumpWidget(
      host(const AiVisualizer(mode: VisualizerMode.generating, color: Colors.cyan, motion: MotionLevel.off)),
    );
    final state = tester.state<AiVisualizerState>(find.byType(AiVisualizer));
    expect(state.animating, isFalse);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.binding.hasScheduledFrame, isFalse); // nothing keeps repainting
    // Switching motion back on starts it again.
    await tester.pumpWidget(host(const AiVisualizer(mode: VisualizerMode.generating, color: Colors.cyan)));
    expect(state.animating, isTrue);
  });

  testWidgets('chat shows the core: large when empty, small in the header while replying', (tester) async {
    final backend = FakeBackend();
    await pumpUltron(tester, backend, signedIn: true);
    expect(find.byType(ChatVisualizer), findsOneWidget);
    expect(tester.getSize(find.byType(AiVisualizer)).width, greaterThan(100));
    expect(find.bySemanticsLabel('ULTRON status: Idle'), findsOneWidget);

    await sendViaUi(tester, 'Hello');
    final seen = <String>{};
    for (var i = 0; i < 30; i++) {
      await tester.pump(const Duration(milliseconds: 20));
      final v = tester.widget<AiVisualizer>(find.byType(AiVisualizer));
      seen.add(v.mode.name);
      if (v.mode == VisualizerMode.generating) expect(v.color, UltronColors.local);
    }
    expect(seen, containsAll(['loadingModel', 'generating']));
    expect(tester.getSize(find.byType(AiVisualizer)).width, 34);
  });

  testWidgets('core dims when the backend is offline', (tester) async {
    final backend = FakeBackend();
    final app = await pumpUltron(tester, backend, signedIn: true);
    backend.online = false;
    await app.container.read(systemStatusProvider.notifier).refresh();
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.widget<AiVisualizer>(find.byType(AiVisualizer)).mode, VisualizerMode.offline);
  });
}
