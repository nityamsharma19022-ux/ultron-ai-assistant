import 'dart:ui';

import 'package:flutter/material.dart';

import '../core/theme/ultron_colors.dart';

/// Frosted, softly glowing panel used across the interface.
class GlassPanel extends StatelessWidget {
  const GlassPanel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(20),
    this.radius = 18,
    this.glow = false,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final double radius;
  final bool glow;

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius),
        boxShadow: glow
            ? [BoxShadow(color: accent.withValues(alpha: 0.18), blurRadius: 32, spreadRadius: -4)]
            : const [],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 14, sigmaY: 14),
          // A gradient replaces a decoration's colour, so the tint is a
          // second layer over the panel fill.
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: UltronColors.panel,
              borderRadius: BorderRadius.circular(radius),
              border: Border.all(color: accent.withValues(alpha: 0.22)),
            ),
            child: DecoratedBox(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(radius),
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [accent.withValues(alpha: 0.06), Colors.transparent],
                ),
              ),
              // Lets list tiles and buttons inside draw their ink ripples.
              child: Material(
                type: MaterialType.transparency,
                child: Padding(padding: padding, child: child),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
