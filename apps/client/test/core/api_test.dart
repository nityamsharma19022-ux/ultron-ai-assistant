import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/api/api_exception.dart';
import 'package:ultron_app/core/api/models.dart';
import 'package:ultron_app/core/api/ultron_api.dart';
import 'package:ultron_app/core/auth/token_store.dart';

import '../support/fake_backend.dart';

void main() {
  late FakeBackend backend;
  late MemoryTokenStore tokens;
  late UltronApi api;

  setUp(() {
    backend = FakeBackend();
    tokens = MemoryTokenStore();
    api = UltronApi(baseUrl: 'http://ultron.test/', tokens: tokens, client: backend.client);
  });

  test('login stores tokens and reuses the device id next time', () async {
    await api.login(email: ownerEmail, password: ownerPassword, deviceName: 'PC', platform: 'windows');
    expect(tokens.tokens!.accessToken, 'access-1');
    expect((backend.bodies['POST /api/v1/auth/login'] as Map).containsKey('device_id'), isFalse);
    await api.login(email: ownerEmail, password: ownerPassword, deviceName: 'PC', platform: 'windows');
    expect((backend.bodies['POST /api/v1/auth/login'] as Map)['device_id'], 'device-1');
  });

  test('wrong password is a 401 with the server message', () async {
    expect(
      () => api.login(email: ownerEmail, password: 'nope', deviceName: 'PC', platform: 'windows'),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 401)),
    );
  });

  test('expired access token is refreshed once and the request retried', () async {
    await tokens.save(TokenPair.fromJson(backend.tokens()));
    backend.expireNextAccessToken = true;
    final me = await api.me();
    expect(me.user.email, ownerEmail);
    expect(backend.refreshCalls, 1);
    expect(tokens.tokens!.refreshToken, 'refresh-2'); // rotated token saved
  });

  test('failed refresh clears tokens and reports 401', () async {
    await tokens.save(const TokenPair(accessToken: 'stale', refreshToken: 'revoked', deviceId: 'device-1'));
    await expectLater(api.me(), throwsA(isA<ApiException>().having((e) => e.isUnauthorized, 'unauthorized', isTrue)));
    expect(tokens.tokens, isNull);
    expect(tokens.deviceId, 'device-1');
  });

  test('network failure becomes a friendly network error', () async {
    backend.online = false;
    await expectLater(
      api.healthLive(),
      throwsA(isA<ApiException>().having((e) => e.isNetwork, 'network', isTrue)),
    );
  });

  test('error details in all backend formats', () async {
    backend.routes['GET /api/v1/x'] = (_, _) async => FakeBackend.json(503, {
      'detail': {'code': 'no_ai_available', 'message': 'No AI provider is available'},
    });
    backend.routes['GET /api/v1/y'] = (_, _) async => FakeBackend.json(422, {
      'detail': [{'msg': 'Value error, must not be empty'}],
    });
    final x = UltronApi(baseUrl: 'http://ultron.test', tokens: tokens, client: backend.client);
    await tokens.save(TokenPair.fromJson(backend.tokens()));
    // Reach the private helper through public calls that hit these routes.
    backend.routes['GET /api/v1/ai/status'] = backend.routes['GET /api/v1/x']!;
    await expectLater(
      x.aiStatus(),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'no_ai_available').having((e) => e.message, 'msg', 'No AI provider is available')),
    );
    backend.routes['GET /api/v1/ai/status'] = backend.routes['GET /api/v1/y']!;
    await expectLater(
      x.aiStatus(),
      throwsA(isA<ApiException>().having((e) => e.message, 'msg', 'Value error, must not be empty')),
    );
  });

  test('readiness is returned even when the server is not ready', () async {
    backend.ready = false;
    final r = await api.healthReady();
    expect(r.ready, isFalse);
    expect(r.checkStatus('database'), 'error');
  });
}
