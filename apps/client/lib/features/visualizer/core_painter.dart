import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'visualizer_mode.dart';

/// Paints the ULTRON core: glow, rotating rings, reactive bars, a breathing
/// centre and orbiting particles. Everything is drawn in code.
class CorePainter extends CustomPainter {
  CorePainter({
    required this.phase,
    required this.style,
    required this.color,
    required this.level,
    required this.detail,
    this.sweep = false,
  });

  /// Animation phase in radians-ish units (already scaled by speed).
  final double phase;
  final VisualizerStyle style;
  final Color color;

  /// Live input level 0–1 (microphone); 0 when unused.
  final double level;

  /// 1 = full detail, 0 = minimal (small sizes / reduced motion).
  final double detail;

  /// Adds a bright sweeping arc (indeterminate loading).
  final bool sweep;

  static const _bars = 56;
  static const _particles = 16;

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final r = math.min(size.width, size.height) / 2;
    final small = r < 40;
    final energy = (style.energy + level * 0.8).clamp(0.0, 1.0);
    final breathe = 1 + style.pulse * 0.06 * math.sin(phase * 1.7);

    // Outer glow.
    canvas.drawCircle(
      c,
      r,
      Paint()
        ..shader = RadialGradient(
          colors: [color.withValues(alpha: 0.30 * style.glow), color.withValues(alpha: 0.08 * style.glow), color.withValues(alpha: 0)],
          stops: const [0.0, 0.55, 1.0],
        ).createShader(Rect.fromCircle(center: c, radius: r)),
    );

    final stroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;

    // Ring 1: long arc, slow.
    stroke
      ..strokeWidth = math.max(1.0, r * 0.012)
      ..color = color.withValues(alpha: 0.55);
    canvas.drawArc(Rect.fromCircle(center: c, radius: r * 0.86), phase * 0.6, math.pi * 1.45, false, stroke);

    if (!small) {
      // Ring 2: three segments, counter-rotating.
      stroke
        ..strokeWidth = math.max(1.5, r * 0.022)
        ..color = color.withValues(alpha: 0.8);
      for (var i = 0; i < 3; i++) {
        canvas.drawArc(
          Rect.fromCircle(center: c, radius: r * 0.73),
          -phase * 0.9 + i * (2 * math.pi / 3),
          math.pi * 0.36,
          false,
          stroke,
        );
      }

      // Ring 3: fine tick marks.
      final tick = Paint()
        ..strokeWidth = 1
        ..color = color.withValues(alpha: 0.28);
      const ticks = 72;
      for (var i = 0; i < ticks; i++) {
        final a = phase * 0.15 + i * 2 * math.pi / ticks;
        final long = i % 6 == 0;
        final inner = r * (long ? 0.60 : 0.615);
        canvas.drawLine(
          c + Offset(math.cos(a), math.sin(a)) * inner,
          c + Offset(math.cos(a), math.sin(a)) * (r * 0.64),
          tick,
        );
      }
    }

    // Loading sweep: a bright comet on the outer ring.
    if (sweep) {
      final rect = Rect.fromCircle(center: c, radius: r * 0.86);
      final start = phase * 1.6;
      stroke
        ..strokeWidth = math.max(2.0, r * 0.03)
        ..shader = SweepGradient(
          startAngle: 0,
          endAngle: math.pi * 0.7,
          colors: [color.withValues(alpha: 0), Colors.white.withValues(alpha: 0.95)],
          transform: GradientRotation(start),
        ).createShader(rect);
      canvas.drawArc(rect, start, math.pi * 0.7, false, stroke);
      stroke.shader = null;
    }

    // Reactive bars around the core.
    final barPaint = Paint()
      ..strokeCap = StrokeCap.round
      ..strokeWidth = math.max(1.2, r * 0.018);
    final bars = small ? 24 : _bars;
    final base = r * 0.40 * breathe;
    for (var i = 0; i < bars; i++) {
      final a = i * 2 * math.pi / bars - math.pi / 2;
      // Three overlapping waves give an organic, voice-like motion.
      final wave =
          0.5 +
          0.25 * math.sin(phase * 3.1 + i * 0.55) +
          0.15 * math.sin(phase * 5.3 - i * 0.31) +
          0.10 * math.sin(phase * 7.7 + i * 1.3);
      final len = r * (0.02 + 0.17 * energy * wave.clamp(0.0, 1.0));
      barPaint.color = color.withValues(alpha: 0.35 + 0.6 * energy * wave.clamp(0.0, 1.0));
      final dir = Offset(math.cos(a), math.sin(a));
      canvas.drawLine(c + dir * base, c + dir * (base + len), barPaint);
    }

    // Core.
    final coreR = r * 0.30 * breathe;
    canvas.drawCircle(
      c,
      coreR,
      Paint()
        ..shader = RadialGradient(
          colors: [
            Colors.white.withValues(alpha: 0.95),
            color.withValues(alpha: 0.85),
            color.withValues(alpha: 0.25),
            color.withValues(alpha: 0),
          ],
          stops: const [0.0, 0.28, 0.7, 1.0],
        ).createShader(Rect.fromCircle(center: c, radius: coreR)),
    );
    canvas.drawCircle(
      c,
      coreR * 0.62,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = math.max(1.0, r * 0.01)
        ..color = Colors.white.withValues(alpha: 0.35 + 0.25 * math.sin(phase * 1.7).abs()),
    );

    // Orbiting particles.
    if (!small && detail > 0.5) {
      final dot = Paint();
      for (var i = 0; i < _particles; i++) {
        final seed = i * 12.9898;
        final orbit = r * (0.66 + 0.30 * _frac(math.sin(seed) * 43758.5453));
        final speed = 0.25 + 0.6 * _frac(math.sin(seed * 1.7) * 24634.6345);
        final a = phase * speed * (i.isEven ? 1 : -1) + seed;
        final twinkle = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(phase * 2.3 + seed));
        dot.color = color.withValues(alpha: 0.75 * twinkle * style.glow);
        canvas.drawCircle(c + Offset(math.cos(a), math.sin(a)) * orbit, math.max(1.0, r * 0.011), dot);
      }
    }
  }

  static double _frac(double v) => v - v.floorToDouble();

  @override
  bool shouldRepaint(CorePainter old) =>
      old.phase != phase ||
      old.color != color ||
      old.level != level ||
      old.sweep != sweep ||
      old.detail != detail ||
      old.style != style;
}
