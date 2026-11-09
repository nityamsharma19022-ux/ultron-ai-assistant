import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:ultron_app/app.dart';
import 'package:ultron_app/core/api/models.dart';
import 'package:ultron_app/core/auth/token_store.dart';
import 'package:ultron_app/core/providers.dart';
import 'package:ultron_app/core/settings/app_settings.dart';
import 'package:ultron_app/features/shell/sections.dart';

const ownerEmail = 'owner@ultron.local';
const ownerPassword = 'correct-horse-battery';

/// In-memory stand-in for ULTRON Core's HTTP API.
class FakeBackend {
  bool online = true;
  bool ready = true;
  bool expireNextAccessToken = false;
  int tokenCounter = 0;
  int refreshCalls = 0;
  final requests = <http.BaseRequest>[];
  final bodies = <String, Object?>{};

  /// Extra routes: (method, path) -> handler returning a streamed response.
  final routes = <String, Future<http.StreamedResponse> Function(http.BaseRequest, String body)>{};

  late final http.Client client = MockClient.streaming((request, bodyStream) async {
    final body = await bodyStream.bytesToString();
    requests.add(request);
    bodies['${request.method} ${request.url.path}'] = body.isEmpty ? null : jsonDecode(body);
    if (!online) throw http.ClientException('Connection refused', request.url);
    final key = '${request.method} ${request.url.path}';
    final custom = routes[key];
    if (custom != null) return custom(request, body);
    return _handle(request, body);
  });

  String get validAccess => 'access-$tokenCounter';

  static http.StreamedResponse json(int status, Object? data) => http.StreamedResponse(
    Stream.value(utf8.encode(jsonEncode(data))),
    status,
    headers: {'content-type': 'application/json'},
  );

  bool authorized(http.BaseRequest r) {
    if (expireNextAccessToken) {
      expireNextAccessToken = false;
      return false;
    }
    return r.headers['Authorization'] == 'Bearer $validAccess';
  }

  Map<String, dynamic> tokens() {
    tokenCounter++;
    return {
      'access_token': validAccess,
      'refresh_token': 'refresh-$tokenCounter',
      'token_type': 'bearer',
      'expires_in': 900,
      'device_id': 'device-1',
    };
  }

  static const me = {
    'user': {'id': 'user-1', 'email': ownerEmail, 'display_name': 'Owner', 'is_owner': true},
    'device': {
      'id': 'device-1',
      'name': 'Windows PC',
      'platform': 'windows',
      'created_at': '2026-11-09T10:00:00Z',
      'last_seen_at': '2026-11-09T10:00:00Z',
      'revoked_at': null,
    },
  };

  static Map<String, dynamic> aiStatus({bool cloud = true, bool local = true}) => {
    'mode': 'auto',
    'cloud_available': cloud,
    'local_ai_available': local,
    'private_conversations_supported': local,
    'providers': [
      {'name': 'groq', 'kind': 'cloud', 'model': 'llama', 'configured': cloud, 'available': cloud, 'status': cloud ? 'ready' : 'not_configured'},
      {'name': 'ollama', 'kind': 'local', 'model': 'qwen3.5:4b', 'configured': true, 'available': local, 'status': local ? 'ready' : 'unavailable', 'model_loaded': local},
    ],
  };

  Future<http.StreamedResponse> _handle(http.BaseRequest r, String body) async {
    final path = r.url.path;
    switch ('${r.method} $path') {
      case 'GET /health/live':
        return json(200, {'status': 'ok', 'service': 'ultron-core', 'version': '0.1.0', 'deployment': 'local', 'node_id': 'ultron-windows-local'});
      case 'GET /health/ready':
        return json(ready ? 200 : 503, {
          'status': ready ? 'ready' : 'not_ready',
          'db_mode': 'local',
          'checks': {
            'database': {'status': ready ? 'ok' : 'error'},
            'redis': {'status': 'ok'},
            'local_ai': {'status': 'ok', 'model': 'qwen3.5:4b'},
          },
        });
      case 'POST /api/v1/auth/login':
        final b = jsonDecode(body) as Map<String, dynamic>;
        if (b['email'] == ownerEmail && b['password'] == ownerPassword) return json(200, tokens());
        return json(401, {'detail': 'Invalid email or password'});
      case 'POST /api/v1/auth/refresh':
        refreshCalls++;
        final b = jsonDecode(body) as Map<String, dynamic>;
        if (b['refresh_token'] == 'refresh-$tokenCounter') return json(200, tokens());
        return json(401, {'detail': 'Not authenticated'});
      case 'POST /api/v1/auth/logout':
        return http.StreamedResponse(const Stream.empty(), 204);
    }
    if (!authorized(r)) return json(401, {'detail': 'Not authenticated'});
    switch ('${r.method} $path') {
      case 'GET /api/v1/auth/me':
        return json(200, me);
      case 'GET /api/v1/ai/status':
        return json(200, aiStatus());
    }
    return json(404, {'detail': 'Not found: ${r.method} $path'});
  }
}

/// Builds the app around [backend] with in-memory storage.
Future<({ProviderContainer container, MemoryTokenStore tokens})> pumpUltron(
  WidgetTester tester,
  FakeBackend backend, {
  Size size = const Size(1280, 800),
  bool signedIn = false,
  Map<AppSection, Widget>? pages,
  Map<String, Object> prefs = const {},
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues(prefs);
  final sp = await SharedPreferences.getInstance();
  final tokens = MemoryTokenStore();
  if (signedIn) {
    final t = backend.tokens();
    await tokens.save(TokenPair.fromJson(t));
  }
  // A real ProviderScope: disposing the widget tree disposes providers (and
  // their timers) before flutter_test checks for pending timers.
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sharedPreferencesProvider.overrideWithValue(sp),
        tokenStoreProvider.overrideWithValue(tokens),
        httpClientProvider.overrideWithValue(backend.client),
      ],
      child: UltronApp(pages: pages),
    ),
  );
  final container = ProviderScope.containerOf(tester.element(find.byType(UltronApp)));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 500));
  return (container: container, tokens: tokens);
}
