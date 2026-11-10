import 'dart:async';

import 'package:ultron_app/core/platform/native.dart';

class FakeAssistantPlatform implements AssistantPlatform {
  FakeAssistantPlatform({this.launchedAsAssist = false, this.isDefault = false});
  bool launchedAsAssist;
  bool isDefault;
  int settingsOpened = 0;
  final _requests = StreamController<void>.broadcast();

  void invoke() => _requests.add(null);

  @override
  bool get supported => true;
  @override
  Future<bool> takeLaunchAssist() async {
    final value = launchedAsAssist;
    launchedAsAssist = false;
    return value;
  }

  @override
  Stream<void> get assistRequests => _requests.stream;
  @override
  Future<bool?> isDefaultAssistant() async => isDefault;
  @override
  Future<void> openAssistantSettings() async => settingsOpened++;
}

class FakePhonePlatform implements PhonePlatform {
  final calls = <(String, Map<String, dynamic>?)>[];
  Map<String, dynamic> Function(String method, Map<String, dynamic>? args) reply = (method, args) => {
    'ok': true,
    'summary': '$method done',
    'verified': true,
  };

  @override
  bool get supported => true;
  @override
  Future<Map<String, dynamic>> call(String method, [Map<String, dynamic>? args]) async {
    calls.add((method, args));
    return Map.of(reply(method, args));
  }

  @override
  Future<List<String>> apps() async => const ['Spotify', 'Camera'];
}
