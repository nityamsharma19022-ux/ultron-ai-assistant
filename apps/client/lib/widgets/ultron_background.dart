import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/settings/app_settings.dart';
import '../core/theme/ultron_colors.dart';

/// Deep-space background with the chosen style (grid, aurora, stars or
/// plain) and a soft accent glow.
class UltronBackground extends ConsumerWidget {
  const UltronBackground({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accent = Theme.of(context).colorScheme.primary;
    final style = ref.watch(settingsProvider.select((s) => s.background));
    final glow = style == BackgroundStyle.plain ? 0.05 : 0.13;
    final painter = switch (style) {
      BackgroundStyle.grid => _GridPainter(),
      BackgroundStyle.stars => _StarsPainter(accent),
      BackgroundStyle.aurora => _AuroraPainter(accent),
      BackgroundStyle.plain => null,
    };
    // Solid base first, then an accent glow that fades to transparent, so
    // the centre is the brightest point.
    return DecoratedBox(
      key: Key('background-${style.name}'),
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [UltronColors.backgroundAlt, UltronColors.background],
        ),
      ),
      child: DecoratedBox(
        decoration: BoxDecoration(
          gradient: RadialGradient(
            center: const Alignment(0, -0.3),
            radius: 0.9,
            colors: [
              accent.withValues(alpha: glow),
              accent.withValues(alpha: glow / 3),
              accent.withValues(alpha: 0),
            ],
            stops: const [0, 0.5, 1],
          ),
        ),
        child: CustomPaint(painter: painter, child: child),
      ),
    );
  }
}

class _GridPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = UltronColors.grid
      ..strokeWidth = 1;
    const step = 48.0;
    for (var x = 0.0; x < size.width; x += step) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (var y = 0.0; y < size.height; y += step) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(_GridPainter oldDelegate) => false;
}

/// Fixed, seeded star field (no animation, so it costs nothing).
class _StarsPainter extends CustomPainter {
  _StarsPainter(this.accent);
  final Color accent;

  @override
  void paint(Canvas canvas, Size size) {
    final rnd = math.Random(7);
    final count = (size.width * size.height / 6000).clamp(40, 400).round();
    final white = Paint()..color = Colors.white.withValues(alpha: 0.5);
    final tinted = Paint()..color = accent.withValues(alpha: 0.6);
    for (var i = 0; i < count; i++) {
      final p = Offset(rnd.nextDouble() * size.width, rnd.nextDouble() * size.height);
      canvas.drawCircle(p, rnd.nextDouble() * 1.2 + 0.2, i % 9 == 0 ? tinted : white);
    }
  }

  @override
  bool shouldRepaint(_StarsPainter old) => old.accent != accent;
}

/// Soft diagonal bands of the accent colour.
class _AuroraPainter extends CustomPainter {
  _AuroraPainter(this.accent);
  final Color accent;

  @override
  void paint(Canvas canvas, Size size) {
    for (var i = 0; i < 3; i++) {
      final rect = Rect.fromLTWH(
        -size.width * 0.2,
        size.height * (0.1 + i * 0.25),
        size.width * 1.4,
        size.height * 0.3,
      );
      final paint = Paint()
        ..shader = LinearGradient(
          colors: [
            accent.withValues(alpha: 0),
            accent.withValues(alpha: 0.07 - i * 0.015),
            accent.withValues(alpha: 0),
          ],
        ).createShader(rect)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 40);
      canvas.save();
      canvas.translate(size.width / 2, size.height / 2);
      canvas.rotate(-0.25 + i * 0.12);
      canvas.translate(-size.width / 2, -size.height / 2);
      canvas.drawOval(rect, paint);
      canvas.restore();
    }
  }

  @override
  bool shouldRepaint(_AuroraPainter old) => old.accent != accent;
}
