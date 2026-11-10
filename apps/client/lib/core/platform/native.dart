import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

bool get isAndroidDevice => !kIsWeb && Platform.isAndroid;

/// The Android assistant integration ("ultron/assistant" channel).
abstract class AssistantPlatform {
  bool get supported;

  /// True once if the app was opened as the phone's assistant.
  Future<bool> takeLaunchAssist();

  /// Assistant invocations while the app is already running.
  Stream<void> get assistRequests;

  /// Null where it can't be known.
  Future<bool?> isDefaultAssistant();

  /// Opens the system screen where the user picks the digital assistant.
  Future<void> openAssistantSettings();
}

class NoAssistantPlatform implements AssistantPlatform {
  const NoAssistantPlatform();
  @override
  bool get supported => false;
  @override
  Future<bool> takeLaunchAssist() async => false;
  @override
  Stream<void> get assistRequests => const Stream.empty();
  @override
  Future<bool?> isDefaultAssistant() async => null;
  @override
  Future<void> openAssistantSettings() async {}
}

class AndroidAssistantPlatform implements AssistantPlatform {
  AndroidAssistantPlatform() {
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'assist') _requests.add(null);
    });
  }
  static const _channel = MethodChannel('ultron/assistant');
  final _requests = StreamController<void>.broadcast();

  @override
  bool get supported => true;
  @override
  Future<bool> takeLaunchAssist() async => await _channel.invokeMethod<bool>('takeLaunchAssist') ?? false;
  @override
  Stream<void> get assistRequests => _requests.stream;
  @override
  Future<bool?> isDefaultAssistant() => _channel.invokeMethod<bool>('isDefaultAssistant');
  @override
  Future<void> openAssistantSettings() => _channel.invokeMethod('openAssistantSettings');
}

final assistantPlatformProvider = Provider<AssistantPlatform>(
  (ref) => isAndroidDevice ? AndroidAssistantPlatform() : const NoAssistantPlatform(),
);

/// Phone actions for the phone.* tools ("ultron/phone" channel).
abstract class PhonePlatform {
  bool get supported;
  Future<Map<String, dynamic>> call(String method, [Map<String, dynamic>? args]);
  Future<List<String>> apps();
}

class NoPhonePlatform implements PhonePlatform {
  const NoPhonePlatform();
  @override
  bool get supported => false;
  @override
  Future<Map<String, dynamic>> call(String method, [Map<String, dynamic>? args]) async => {
    'ok': false,
    'error': 'Not available on this device',
  };
  @override
  Future<List<String>> apps() async => const [];
}

class AndroidPhonePlatform implements PhonePlatform {
  static const _channel = MethodChannel('ultron/phone');
  @override
  bool get supported => true;
  @override
  Future<Map<String, dynamic>> call(String method, [Map<String, dynamic>? args]) async {
    final result = await _channel.invokeMethod<Object?>(method, args);
    return result is Map ? result.cast<String, dynamic>() : {'ok': true, 'value': result};
  }

  @override
  Future<List<String>> apps() async => [
    for (final a in await _channel.invokeMethod<List<Object?>>('apps') ?? const []) '$a',
  ];
}

final phonePlatformProvider = Provider<PhonePlatform>(
  (ref) => isAndroidDevice ? AndroidPhonePlatform() : const NoPhonePlatform(),
);
