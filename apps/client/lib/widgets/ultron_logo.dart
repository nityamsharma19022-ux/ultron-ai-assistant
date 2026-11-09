import 'package:flutter/material.dart';

/// Wordmark: a small ring emblem and "ULTRON" in the display font.
class UltronLogo extends StatelessWidget {
  const UltronLogo({super.key, this.size = 22, this.showWordmark = true});
  final double size;
  final bool showWordmark;

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    final emblem = Container(
      width: size * 1.4,
      height: size * 1.4,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: accent, width: 2),
        boxShadow: [BoxShadow(color: accent.withValues(alpha: 0.6), blurRadius: size * 0.8)],
      ),
      child: Center(
        child: Container(
          width: size * 0.45,
          height: size * 0.45,
          decoration: BoxDecoration(shape: BoxShape.circle, color: accent),
        ),
      ),
    );
    if (!showWordmark) return emblem;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        emblem,
        SizedBox(width: size * 0.6),
        Text(
          'ULTRON',
          style: TextStyle(
            fontFamily: 'Orbitron',
            fontWeight: FontWeight.w700,
            fontSize: size,
            letterSpacing: size * 0.25,
            color: Colors.white,
            shadows: [Shadow(color: accent.withValues(alpha: 0.7), blurRadius: 16)],
          ),
        ),
      ],
    );
  }
}
