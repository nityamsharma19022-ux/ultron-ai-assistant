import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app.dart';
import 'core/settings/app_settings.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  LicenseRegistry.addLicense(_fontLicences);
  final prefs = await SharedPreferences.getInstance();
  runApp(ProviderScope(overrides: [sharedPreferencesProvider.overrideWithValue(prefs)], child: const UltronApp()));
}

/// The bundled fonts are under the SIL Open Font License; show it in the
/// app's licence page.
Stream<LicenseEntry> _fontLicences() async* {
  for (final (font, file) in [('Orbitron', 'OFL-orbitron.txt'), ('Inter', 'OFL-inter.txt')]) {
    yield LicenseEntryWithLineBreaks([font], await rootBundle.loadString('assets/fonts/$file'));
  }
}
