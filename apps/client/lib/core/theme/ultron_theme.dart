import 'package:flutter/material.dart';

import 'ultron_colors.dart';

/// Builds the dark theme around the chosen accent colour.
ThemeData buildUltronTheme(Color accent) {
  final scheme = ColorScheme.fromSeed(seedColor: accent, brightness: Brightness.dark).copyWith(
    primary: accent,
    secondary: accent,
    surface: UltronColors.surface,
    onSurface: UltronColors.textPrimary,
    error: UltronColors.danger,
  );

  const display = TextStyle(fontFamily: 'Orbitron', letterSpacing: 2.0, color: UltronColors.textPrimary);
  final base = ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: scheme,
    fontFamily: 'Inter',
    scaffoldBackgroundColor: UltronColors.background,
    canvasColor: UltronColors.background,
  );

  return base.copyWith(
    textTheme: base.textTheme
        .apply(bodyColor: UltronColors.textPrimary, displayColor: UltronColors.textPrimary)
        .copyWith(
          displaySmall: display.copyWith(fontSize: 30, fontWeight: FontWeight.w700),
          headlineSmall: display.copyWith(fontSize: 20, fontWeight: FontWeight.w700),
          titleLarge: display.copyWith(fontSize: 16, fontWeight: FontWeight.w500),
          labelSmall: const TextStyle(
            fontFamily: 'Inter',
            fontSize: 11,
            letterSpacing: 1.2,
            color: UltronColors.textSecondary,
          ),
        ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: const Color(0x66070D18),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: UltronColors.panelBorder),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: UltronColors.panelBorder),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: accent, width: 1.4),
      ),
      labelStyle: const TextStyle(color: UltronColors.textSecondary),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: accent,
        foregroundColor: UltronColors.background,
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: const TextStyle(fontWeight: FontWeight.w600, letterSpacing: 0.6),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: accent,
        side: BorderSide(color: accent.withValues(alpha: 0.5)),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    ),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: UltronColors.surface,
      contentTextStyle: TextStyle(color: UltronColors.textPrimary),
      behavior: SnackBarBehavior.floating,
    ),
    dividerColor: UltronColors.panelBorder,
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {
        TargetPlatform.android: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.windows: FadeForwardsPageTransitionsBuilder(),
      },
    ),
  );
}
