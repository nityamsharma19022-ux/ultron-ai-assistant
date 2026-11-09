import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:ultron_app/core/settings/app_settings.dart';
import 'package:ultron_app/core/theme/ultron_colors.dart';

void main() {
  test('backend address validation', () {
    expect(validateBackendUrl('http://127.0.0.1:8000'), isNull);
    expect(validateBackendUrl('https://ultron.example.com'), isNull);
    expect(validateBackendUrl('http://192.168.1.20:8000/'), isNull);
    expect(validateBackendUrl('127.0.0.1:8000'), isNotNull);
    expect(validateBackendUrl('ftp://host'), isNotNull);
    expect(validateBackendUrl('http://host:8000/api/v1'), isNotNull);
    expect(normalizeBackendUrl(' http://127.0.0.1:8000/ '), 'http://127.0.0.1:8000');
  });

  test('settings persist and reload', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final c = ProviderContainer(overrides: [sharedPreferencesProvider.overrideWithValue(prefs)]);
    addTearDown(c.dispose);
    final n = c.read(settingsProvider.notifier);
    await n.setBackendUrl('http://192.168.1.20:8000/');
    await n.setAccent(UltronAccent.violet);
    await n.setMotion(MotionLevel.reduced);
    await n.setSpeakReplies(true);

    final again = ProviderContainer(overrides: [sharedPreferencesProvider.overrideWithValue(prefs)]);
    addTearDown(again.dispose);
    final s = again.read(settingsProvider);
    expect(s.backendUrl, 'http://192.168.1.20:8000');
    expect(s.accent, UltronAccent.violet);
    expect(s.motion, MotionLevel.reduced);
    expect(s.speakReplies, isTrue);
  });
}
