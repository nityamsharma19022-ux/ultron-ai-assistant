import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../theme/ultron_colors.dart';

/// How much animation the interface uses.
enum MotionLevel {
  full('Full'),
  reduced('Reduced'),
  off('Off');

  const MotionLevel(this.label);
  final String label;

  static MotionLevel fromName(String? name) =>
      MotionLevel.values.firstWhere((m) => m.name == name, orElse: () => MotionLevel.full);
}

/// Non-secret, per-device preferences. Login tokens live in secure storage
/// (see token_store.dart), never here.
@immutable
class AppSettings {
  const AppSettings({
    required this.backendUrl,
    this.accent = UltronAccent.cyan,
    this.motion = MotionLevel.full,
    this.speakReplies = false,
    this.speechRate = 0.5,
    this.voiceLocale,
  });

  final String backendUrl;
  final UltronAccent accent;
  final MotionLevel motion;
  final bool speakReplies;
  final double speechRate;
  final String? voiceLocale;

  AppSettings copyWith({
    String? backendUrl,
    UltronAccent? accent,
    MotionLevel? motion,
    bool? speakReplies,
    double? speechRate,
    String? voiceLocale,
  }) => AppSettings(
    backendUrl: backendUrl ?? this.backendUrl,
    accent: accent ?? this.accent,
    motion: motion ?? this.motion,
    speakReplies: speakReplies ?? this.speakReplies,
    speechRate: speechRate ?? this.speechRate,
    voiceLocale: voiceLocale ?? this.voiceLocale,
  );
}

/// Default backend address. The Android emulator reaches the PC via
/// 10.0.2.2; a real phone needs the PC's LAN address (set on the sign-in
/// screen).
String defaultBackendUrl() =>
    defaultTargetPlatform == TargetPlatform.android ? 'http://10.0.2.2:8000' : 'http://127.0.0.1:8000';

/// Returns an error message, or null if [value] is a usable backend address.
String? validateBackendUrl(String value) {
  final uri = Uri.tryParse(value.trim());
  if (uri == null || !(uri.scheme == 'http' || uri.scheme == 'https') || uri.host.isEmpty) {
    return 'Enter an address like http://127.0.0.1:8000';
  }
  if (uri.path.isNotEmpty && uri.path != '/') return 'Use the server address only, without a path';
  return null;
}

String normalizeBackendUrl(String value) => value.trim().replaceAll(RegExp(r'/+$'), '');

final sharedPreferencesProvider = Provider<SharedPreferences>(
  (ref) => throw UnimplementedError('sharedPreferencesProvider is overridden in main()'),
);

final settingsProvider = NotifierProvider<SettingsController, AppSettings>(SettingsController.new);

class SettingsController extends Notifier<AppSettings> {
  static const _kBackend = 'backend_url';
  static const _kAccent = 'accent';
  static const _kMotion = 'motion';
  static const _kSpeak = 'speak_replies';
  static const _kRate = 'speech_rate';
  static const _kLocale = 'voice_locale';

  SharedPreferences get _prefs => ref.read(sharedPreferencesProvider);

  @override
  AppSettings build() {
    final p = ref.watch(sharedPreferencesProvider);
    return AppSettings(
      backendUrl: p.getString(_kBackend) ?? defaultBackendUrl(),
      accent: UltronAccent.fromName(p.getString(_kAccent)),
      motion: MotionLevel.fromName(p.getString(_kMotion)),
      speakReplies: p.getBool(_kSpeak) ?? false,
      speechRate: p.getDouble(_kRate) ?? 0.5,
      voiceLocale: p.getString(_kLocale),
    );
  }

  Future<void> setBackendUrl(String url) async {
    final value = normalizeBackendUrl(url);
    await _prefs.setString(_kBackend, value);
    state = state.copyWith(backendUrl: value);
  }

  Future<void> setAccent(UltronAccent accent) async {
    await _prefs.setString(_kAccent, accent.name);
    state = state.copyWith(accent: accent);
  }

  Future<void> setMotion(MotionLevel motion) async {
    await _prefs.setString(_kMotion, motion.name);
    state = state.copyWith(motion: motion);
  }

  Future<void> setSpeakReplies(bool value) async {
    await _prefs.setBool(_kSpeak, value);
    state = state.copyWith(speakReplies: value);
  }

  Future<void> setSpeechRate(double value) async {
    await _prefs.setDouble(_kRate, value);
    state = state.copyWith(speechRate: value);
  }

  Future<void> setVoiceLocale(String? localeId) async {
    if (localeId == null) {
      await _prefs.remove(_kLocale);
      state = AppSettings(
        backendUrl: state.backendUrl,
        accent: state.accent,
        motion: state.motion,
        speakReplies: state.speakReplies,
        speechRate: state.speechRate,
      );
      return;
    }
    await _prefs.setString(_kLocale, localeId);
    state = state.copyWith(voiceLocale: localeId);
  }
}
