import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../api/models.dart';

/// Where login tokens are kept.
abstract class TokenStore {
  Future<TokenPair?> read();
  Future<void> save(TokenPair tokens);
  Future<void> clear();

  /// The device id survives sign-out so a re-login keeps the same device.
  Future<String?> readDeviceId();
}

/// Tokens in the OS secure store: Windows Credential Manager on Windows,
/// Android Keystore-backed storage on Android.
class SecureTokenStore implements TokenStore {
  SecureTokenStore([FlutterSecureStorage? storage]) : _s = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _s;
  static const _access = 'ultron_access_token';
  static const _refresh = 'ultron_refresh_token';
  static const _device = 'ultron_device_id';

  @override
  Future<TokenPair?> read() async {
    final a = await _s.read(key: _access);
    final r = await _s.read(key: _refresh);
    final d = await _s.read(key: _device);
    if (a == null || r == null || d == null) return null;
    return TokenPair(accessToken: a, refreshToken: r, deviceId: d);
  }

  @override
  Future<void> save(TokenPair t) async {
    await _s.write(key: _access, value: t.accessToken);
    await _s.write(key: _refresh, value: t.refreshToken);
    await _s.write(key: _device, value: t.deviceId);
  }

  @override
  Future<void> clear() async {
    await _s.delete(key: _access);
    await _s.delete(key: _refresh);
  }

  @override
  Future<String?> readDeviceId() => _s.read(key: _device);
}

/// In-memory store for tests.
class MemoryTokenStore implements TokenStore {
  TokenPair? tokens;
  String? deviceId;

  @override
  Future<TokenPair?> read() async => tokens;

  @override
  Future<void> save(TokenPair t) async {
    tokens = t;
    deviceId = t.deviceId;
  }

  @override
  Future<void> clear() async => tokens = null;

  @override
  Future<String?> readDeviceId() async => deviceId;
}
