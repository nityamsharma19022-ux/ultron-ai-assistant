import 'package:flutter/material.dart';

/// ULTRON's colour palette: deep space background, glass panels and one
/// configurable accent glow.
abstract final class UltronColors {
  static const background = Color(0xFF03060C);
  static const backgroundAlt = Color(0xFF070D18);
  static const surface = Color(0xFF0B1424);
  static const panel = Color(0x9910192C);
  static const panelBorder = Color(0x3346E0F5);
  static const grid = Color(0x1422D3EE);
  static const textPrimary = Color(0xFFE6F1FF);
  static const textSecondary = Color(0xFF8AA0BE);
  static const textMuted = Color(0xFF55667F);

  /// Where a reply came from.
  static const cloud = Color(0xFF60A5FA);
  static const local = Color(0xFF34D399);

  static const success = Color(0xFF34D399);
  static const warning = Color(0xFFFBBF24);
  static const danger = Color(0xFFF87171);
}

/// Accent colours the user can choose in Settings.
enum UltronAccent {
  cyan('Cyan', Color(0xFF22D3EE)),
  violet('Violet', Color(0xFFA78BFA)),
  amber('Amber', Color(0xFFFBBF24)),
  emerald('Emerald', Color(0xFF34D399)),
  crimson('Crimson', Color(0xFFF43F5E));

  const UltronAccent(this.label, this.color);
  final String label;
  final Color color;

  static UltronAccent fromName(String? name) =>
      UltronAccent.values.firstWhere((a) => a.name == name, orElse: () => UltronAccent.cyan);
}
