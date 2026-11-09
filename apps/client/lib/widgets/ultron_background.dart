import 'package:flutter/material.dart';

import '../core/theme/ultron_colors.dart';

/// Deep-space background with a faint grid and a soft accent glow.
class UltronBackground extends StatelessWidget {
  const UltronBackground({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    // Solid base first, then an accent glow that fades to transparent, so
    // the centre is the brightest point.
    return DecoratedBox(
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
            colors: [accent.withValues(alpha: 0.13), accent.withValues(alpha: 0.04), accent.withValues(alpha: 0)],
            stops: const [0, 0.5, 1],
          ),
        ),
        child: CustomPaint(painter: _GridPainter(), child: child),
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
