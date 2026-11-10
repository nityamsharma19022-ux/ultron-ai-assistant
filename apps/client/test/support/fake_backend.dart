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
import 'package:ultron_app/features/voice/speech_engines.dart';
import 'package:ultron_app/features/voice/voice_controller.dart';

import 'fake_voice.dart';

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
      {
        'name': 'groq',
        'kind': 'cloud',
        'model': 'llama',
        'configured': cloud,
        'available': cloud,
        'status': cloud ? 'ready' : 'not_configured',
      },
      {
        'name': 'ollama',
        'kind': 'local',
        'model': 'qwen3.5:4b',
        'configured': true,
        'available': local,
        'status': local ? 'ready' : 'unavailable',
        'model_loaded': local,
      },
    ],
  };

  // ---------------------------------------------------- devices, AI prefs
  final devices = <Map<String, dynamic>>[
    Map.of(me['device']! as Map<String, dynamic>),
    {
      'id': 'device-2',
      'name': 'Pixel phone',
      'platform': 'android',
      'created_at': '2026-11-08T09:00:00Z',
      'last_seen_at': '2026-11-09T18:30:00Z',
      'revoked_at': null,
    },
  ];
  Map<String, dynamic> preferences = {
    'mode': 'auto',
    'cloud_order': ['groq', 'gemini'],
    'private_by_default': false,
    'available_cloud_providers': ['groq', 'gemini', 'openrouter'],
  };
  int preferenceSaves = 0;

  /// Status and body returned by the warm-up route.
  int warmupStatus = 200;
  Map<String, dynamic> warmupBody = {
    'status': 'ready',
    'provider': 'ollama',
    'model': 'qwen3.5:4b',
    'already_loaded': false,
    'seconds': 2.5,
  };

  Future<http.StreamedResponse>? _extras(http.BaseRequest r, String body) {
    final path = r.url.path;
    final revoke = RegExp(r'^/api/v1/devices/([^/]+)$').firstMatch(path);
    if (revoke != null && r.method == 'DELETE') {
      final d = devices.where((x) => x['id'] == revoke.group(1)).firstOrNull;
      if (d == null) return Future.value(json(404, {'detail': 'Device not found'}));
      d['revoked_at'] = '2026-11-10T12:00:00Z';
      return Future.value(http.StreamedResponse(const Stream.empty(), 204));
    }
    switch ('${r.method} $path') {
      case 'GET /api/v1/devices':
        return Future.value(json(200, devices));
      case 'GET /api/v1/ai/preferences':
        return Future.value(json(200, preferences));
      case 'PUT /api/v1/ai/preferences':
        final b = jsonDecode(body) as Map<String, dynamic>;
        preferenceSaves++;
        preferences = {...preferences, ...b};
        return Future.value(json(200, preferences));
      case 'POST /api/v1/ai/local/warmup':
        return Future.value(json(warmupStatus, warmupBody));
    }
    return null;
  }

  // ------------------------------------------------------------ chat
  final conversations = <Map<String, dynamic>>[];
  final messages = <String, List<Map<String, dynamic>>>{};
  int cancelCalls = 0;
  int _ids = 0;

  /// SSE events for the next reply: (event, data). Use [defaultReply].
  List<(String, Map<String, dynamic>)> Function(String conversationId, String content)? replyScript;

  /// When set, the stream pauses after the status events until completed.
  Completer<void>? holdReply;

  /// Status code to answer the message POST with instead of streaming.
  int? messageStatus;
  Map<String, dynamic>? messageError;

  String nextId() => '00000000-0000-0000-0000-${(++_ids).toString().padLeft(12, '0')}';

  Map<String, dynamic> message(
    String role,
    String content, {
    String status = 'complete',
    String? kind,
    String? provider,
    String? model,
    String? id,
    String? errorCode,
  }) => {
    'id': id ?? nextId(),
    'role': role,
    'content': content,
    'status': status,
    'provider': provider,
    'provider_kind': kind,
    'model': model,
    'fallback_used': false,
    'error_code': errorCode,
    'created_at': '2026-11-09T10:00:00Z',
  };

  Map<String, dynamic> addConversation({String? title, bool private = false}) {
    final c = {
      'id': nextId(),
      'title': title,
      'is_private': private,
      'created_at': '2026-11-09T10:00:00Z',
      'updated_at': '2026-11-09T10:00:00Z',
    };
    conversations.insert(0, c);
    messages[c['id'] as String] = [];
    return c;
  }

  static List<(String, Map<String, dynamic>)> defaultReply(String assistantId, {String kind = 'local'}) => [
    ('status', {'phase': 'routing'}),
    (
      'status',
      {'phase': 'loading_model', 'provider': 'ollama', 'kind': kind, 'model': 'qwen3.5:4b', 'model_loaded': false},
    ),
    (
      'provider.selected',
      {'provider': 'ollama', 'kind': kind, 'model': 'qwen3.5:4b', 'fallback_used': false, 'attempts': []},
    ),
    ('status', {'phase': 'generating', 'provider': 'ollama', 'kind': kind, 'model': 'qwen3.5:4b'}),
    ('delta', {'text': 'Hello'}),
    ('delta', {'text': ' from'}),
    ('delta', {'text': ' ULTRON'}),
  ];

  Future<http.StreamedResponse> _messages(http.BaseRequest r, String conversationId, String body) async {
    if (messageStatus != null) return json(messageStatus!, {'detail': messageError ?? 'error'});
    final content = (jsonDecode(body) as Map)['content'] as String;
    final user = message('user', content);
    final assistantId = nextId();
    messages[conversationId]!.add(user);
    final c = conversations.firstWhere((x) => x['id'] == conversationId);
    c['title'] ??= content;
    final script = replyScript?.call(conversationId, content) ?? defaultReply(assistantId);
    final hold = holdReply;
    final controller = StreamController<List<int>>();
    String sse(String e, Map<String, dynamic> d) => 'event: $e\ndata: ${jsonEncode(d)}\n\n';
    () async {
      controller.add(
        utf8.encode(
          sse('message.created', {
            'user_message': user,
            'assistant_message_id': assistantId,
            'private': c['is_private'],
          }),
        ),
      );
      final text = StringBuffer();
      String? kind;
      var cancelled = false;
      for (final (e, d) in script) {
        if (e == 'delta' && hold != null && !hold.isCompleted) {
          await hold.future;
          cancelled = cancelCalls > 0;
          if (cancelled) break;
        }
        await Future<void>.delayed(const Duration(milliseconds: 20));
        if (e == 'delta') text.write(d['text']);
        if (e == 'provider.selected') kind = d['kind'] as String?;
        controller.add(utf8.encode(sse(e, d)));
        if (e == 'error') {
          await controller.close();
          return;
        }
      }
      final final_ = message(
        'assistant',
        text.toString(),
        id: assistantId,
        status: cancelled ? 'cancelled' : 'complete',
        kind: kind,
        provider: kind == null ? null : 'ollama',
        model: kind == null ? null : 'qwen3.5:4b',
      );
      messages[conversationId]!.add(final_);
      controller.add(
        utf8.encode(
          cancelled
              ? sse('message.cancelled', {'assistant_message': final_, 'routing': null})
              : sse('message.completed', {
                  'assistant_message': final_,
                  'routing': {'kind': kind},
                }),
        ),
      );
      await controller.close();
    }();
    return http.StreamedResponse(controller.stream, 200, headers: {'content-type': 'text/event-stream'});
  }

  Future<http.StreamedResponse>? _chat(http.BaseRequest r, String body) {
    final path = r.url.path;
    final m = RegExp(r'^/api/v1/conversations/([^/]+)(/messages|/cancel)?$').firstMatch(path);
    if (path == '/api/v1/conversations' && r.method == 'GET') return Future.value(json(200, conversations));
    if (path == '/api/v1/conversations' && r.method == 'POST') {
      final b = body.isEmpty ? <String, dynamic>{} : jsonDecode(body) as Map<String, dynamic>;
      return Future.value(json(201, addConversation(title: b['title'] as String?, private: b['is_private'] == true)));
    }
    if (m == null) return null;
    final id = m.group(1)!;
    final c = conversations.where((x) => x['id'] == id).firstOrNull;
    if (c == null) return Future.value(json(404, {'detail': 'Conversation not found'}));
    switch ((r.method, m.group(2))) {
      case ('GET', null):
        return Future.value(json(200, {'conversation': c, 'messages': messages[id]}));
      case ('PATCH', null):
        final b = jsonDecode(body) as Map<String, dynamic>;
        if (b['is_private'] == true) c['is_private'] = true;
        if (b['title'] != null) c['title'] = b['title'];
        return Future.value(json(200, c));
      case ('DELETE', null):
        conversations.remove(c);
        return Future.value(http.StreamedResponse(const Stream.empty(), 204));
      case ('POST', '/messages'):
        return _messages(r, id, body);
      case ('POST', '/cancel'):
        cancelCalls++;
        if (holdReply != null && !holdReply!.isCompleted) holdReply!.complete();
        return Future.value(json(202, {'status': 'cancelling'}));
    }
    return null;
  }

  Future<http.StreamedResponse> _handle(http.BaseRequest r, String body) async {
    final path = r.url.path;
    switch ('${r.method} $path') {
      case 'GET /health/live':
        return json(200, {
          'status': 'ok',
          'service': 'ultron-core',
          'version': '0.1.0',
          'deployment': 'local',
          'node_id': 'ultron-windows-local',
        });
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
    final chat = _chat(r, body) ?? _extras(r, body);
    if (chat != null) return chat;
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
  SpeechInput? speechInput,
  SpeechOutput? speechOutput,
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
        speechInputProvider.overrideWithValue(speechInput ?? FakeSpeechInput()),
        speechOutputProvider.overrideWithValue(speechOutput ?? FakeSpeechOutput()),
      ],
      child: UltronApp(pages: pages),
    ),
  );
  final container = ProviderScope.containerOf(tester.element(find.byType(UltronApp)));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 500));
  return (container: container, tokens: tokens);
}
