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
import 'package:ultron_app/core/platform/native.dart';
import 'package:ultron_app/features/documents/documents.dart';
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
    Object? decoded;
    try {
      decoded = body.isEmpty ? null : jsonDecode(body);
    } on FormatException {
      decoded = body; // multipart uploads
    }
    bodies['${request.method} ${request.url.path}'] = decoded;
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

  // ------------------------------------------------- tasks, memory, agents
  final tasks = <Map<String, dynamic>>[];
  final memories = <Map<String, dynamic>>[];
  final activity = <Map<String, dynamic>>[];
  final agents = <Map<String, dynamic>>[];
  final dueReminders = <Map<String, dynamic>>[];
  final deliveredReminders = <String>[];
  final stepResults = <String, Map<String, dynamic>>{};
  final pendingSteps = <Map<String, dynamic>>[];
  Map<String, dynamic>? agentHelloBody;
  bool automationEnabled = true;
  bool automationStopped = false;
  final grants = <String>{};
  final commands = <String>[];
  final documents = <Map<String, dynamic>>[];
  final uploads = <String>[];

  /// How /assistant/command answers; default: a completed one-step task.
  Map<String, dynamic> Function(String text) commandReply = (text) => {
    'type': 'answer',
    'message': 'You said: $text',
    'task': null,
  };

  static const permissionCatalog = [
    ('memory.write', 'Save memories', false),
    ('reminders', 'Create reminders', false),
    ('pc.apps', 'Open and switch apps on the PC', false),
    ('pc.files.organize', 'Move and organize files in allowed PC folders', false),
    ('pc.files.delete', 'Move files to the Recycle Bin (always asks)', true),
    ('phone.apps', 'Open apps on the phone', false),
  ];

  Map<String, dynamic> task(String id, String title, String status, List<Map<String, dynamic>> steps) => {
    'id': id,
    'title': title,
    'request': title,
    'status': status,
    'plan_source': 'rules',
    'is_private': false,
    'summary': null,
    'error': null,
    'schedule_id': null,
    'created_at': '2026-11-10T10:00:00Z',
    'updated_at': '2026-11-10T10:00:00Z',
    'started_at': null,
    'finished_at': null,
    'steps': steps,
  };

  static Map<String, dynamic> step(
    String id,
    String title,
    String status, {
    String tool = 'pc.apps.open',
    String risk = 'A',
    String target = 'windows',
    Map<String, dynamic>? result,
  }) => {
    'id': id,
    'idx': 0,
    'tool': tool,
    'args': <String, dynamic>{},
    'title': title,
    'target': target,
    'risk': risk,
    'scope': 'pc.apps',
    'status': status,
    'approved': false,
    'attempts': 0,
    'max_attempts': 2,
    'result': result,
    'error': null,
    'progress': null,
    'started_at': null,
    'finished_at': null,
  };

  Map<String, dynamic> _automation() => {
    'enabled': automationEnabled,
    'stopped': automationStopped,
    'stopped_at': null,
  };

  Future<http.StreamedResponse>? _more(http.BaseRequest r, String body) {
    final path = r.url.path;
    final key = '${r.method} $path';
    Map<String, dynamic> b() => body.isEmpty ? <String, dynamic>{} : jsonDecode(body) as Map<String, dynamic>;
    Future<http.StreamedResponse> ok(Object? data, [int status = 200]) => Future.value(json(status, data));
    final taskAction = RegExp(r'^/api/v1/tasks/([^/]+)/(approve|reject|cancel|pause|resume|retry|repeat)$')
        .firstMatch(path);
    if (taskAction != null) {
      final t = tasks.firstWhere((x) => x['id'] == taskAction.group(1));
      switch (taskAction.group(2)) {
        case 'approve':
          if (b()['remember'] == true) grants.add('pc.apps');
          t['status'] = 'completed';
          for (final s in t['steps'] as List) {
            (s as Map)['status'] = 'succeeded';
          }
        case 'reject' || 'cancel':
          t['status'] = 'cancelled';
        case 'pause':
          t['status'] = 'paused';
        case 'resume' || 'retry':
          t['status'] = 'queued';
        case 'repeat':
          return ok({'id': 'sched-1'}, 201);
      }
      return ok(t);
    }
    final perm = RegExp(r'^/api/v1/permissions/(.+)$').firstMatch(path);
    if (perm != null && r.method == 'PUT') {
      final scope = perm.group(1)!;
      b()['enabled'] == true ? grants.add(scope) : grants.remove(scope);
      final entry = permissionCatalog.firstWhere((e) => e.$1 == scope);
      return ok({
        'scope': scope,
        'title': entry.$2,
        'granted': grants.contains(scope),
        'always_asks': entry.$3,
        'expires_at': null,
        'tools': <String>[],
      });
    }
    final memory = RegExp(r'^/api/v1/memories/([^/]+)$').firstMatch(path);
    if (memory != null && memory.group(1) != 'export') {
      final m = memories.firstWhere((x) => x['id'] == memory.group(1));
      if (r.method == 'DELETE') {
        memories.remove(m);
        return Future.value(http.StreamedResponse(const Stream.empty(), 204));
      }
      final u = b();
      for (final k in ['content', 'kind', 'pinned', 'is_private']) {
        if (u.containsKey(k)) m[k] = u[k];
      }
      return ok(m);
    }
    final reminder = RegExp(r'^/api/v1/reminders/([^/]+)$').firstMatch(path);
    if (reminder != null && r.method == 'PATCH') {
      deliveredReminders.add(reminder.group(1)!);
      dueReminders.removeWhere((x) => x['id'] == reminder.group(1));
      return ok({'id': reminder.group(1), 'text': '', 'due_at': '2026-11-10T10:00:00Z', 'done': false});
    }
    final result = RegExp(r'^/api/v1/agents/steps/([^/]+)/result$').firstMatch(path);
    if (result != null) {
      stepResults[result.group(1)!] = b();
      return ok({'cancel': false});
    }
    final document = RegExp(r'^/api/v1/documents/([^/]+)$').firstMatch(path);
    if (document != null && r.method == 'DELETE') {
      documents.removeWhere((d) => d['id'] == document.group(1));
      return Future.value(http.StreamedResponse(const Stream.empty(), 204));
    }
    switch (key) {
      case 'GET /api/v1/documents':
        return ok(documents);
      case 'POST /api/v1/documents':
        final name = RegExp(r'filename="([^"]+)"').firstMatch(body)?.group(1) ?? 'file';
        uploads.add(name);
        final d = {
          'id': 'doc-${documents.length + 1}',
          'name': name,
          'kind': name.endsWith('.pdf') ? 'pdf' : 'text',
          'size': 2048,
          'pages': name.endsWith('.pdf') ? 3 : null,
          'chars': 900,
          'chunk_count': 2,
          'is_private': body.contains('name="is_private"\r\n\r\ntrue'),
          'source': 'upload',
          'created_at': '2026-11-10T10:00:00Z',
          'reused': false,
        };
        documents.insert(0, d);
        return ok(d, 201);
      case 'POST /api/v1/assistant/command':
        final text = b()['text'] as String;
        commands.add(text);
        final reply = commandReply(text);
        if (reply['task'] != null) tasks.insert(0, reply['task'] as Map<String, dynamic>);
        return ok(reply);
      case 'GET /api/v1/tasks':
        return ok(tasks);
      case 'GET /api/v1/permissions':
        return ok([
          for (final e in permissionCatalog)
            {
              'scope': e.$1,
              'title': e.$2,
              'granted': grants.contains(e.$1),
              'always_asks': e.$3,
              'expires_at': null,
              'tools': <String>[],
            },
        ]);
      case 'GET /api/v1/automation':
        return ok(_automation());
      case 'PUT /api/v1/automation':
        final u = b();
        if (u['enabled'] != null) automationEnabled = u['enabled'] as bool;
        if (u['stopped'] == false) automationStopped = false;
        return ok(_automation());
      case 'POST /api/v1/automation/emergency-stop':
        automationStopped = true;
        for (final t in tasks) {
          if (t['status'] != 'completed') t['status'] = 'cancelled';
        }
        return ok(_automation());
      case 'GET /api/v1/activity':
        return ok(activity);
      case 'GET /api/v1/memories':
        final q = r.url.queryParameters['q']?.toLowerCase();
        return ok([
          for (final m in memories)
            if (q == null || (m['content'] as String).toLowerCase().contains(q)) m,
        ]);
      case 'POST /api/v1/memories':
        final u = b();
        final m = {
          'id': 'mem-${memories.length + 1}',
          'content': u['content'],
          'kind': u['kind'] ?? 'note',
          'source': 'user',
          'is_private': u['is_private'] ?? false,
          'pinned': u['pinned'] ?? false,
          'last_used_at': null,
          'created_at': '2026-11-10T10:00:00Z',
          'updated_at': '2026-11-10T10:00:00Z',
        };
        memories.insert(0, m);
        return ok(m, 201);
      case 'GET /api/v1/memories/export':
        return ok({'exported_at': '2026-11-10T10:00:00Z', 'count': memories.length, 'memories': memories});
      case 'DELETE /api/v1/memories':
        final n = memories.length;
        memories.clear();
        return ok({'deleted': n});
      case 'GET /api/v1/agents':
        return ok(agents);
      case 'POST /api/v1/agents/hello':
        agentHelloBody = b();
        return ok({});
      case 'GET /api/v1/agents/steps/next':
        if (pendingSteps.isEmpty) return Future.value(http.StreamedResponse(const Stream.empty(), 204));
        return ok(pendingSteps.removeAt(0));
      case 'GET /api/v1/reminders':
        return ok(r.url.queryParameters['due'] == 'true' ? dueReminders : <Object>[]);
    }
    return null;
  }

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
    final chat = _chat(r, body) ?? _extras(r, body) ?? _more(r, body);
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
  AssistantPlatform? assistantPlatform,
  PhonePlatform? phonePlatform,
  FileSource? fileSource,
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
        assistantPlatformProvider.overrideWithValue(assistantPlatform ?? const NoAssistantPlatform()),
        phonePlatformProvider.overrideWithValue(phonePlatform ?? const NoPhonePlatform()),
        fileSourceProvider.overrideWithValue(fileSource ?? const _NoFiles()),
      ],
      child: UltronApp(pages: pages),
    ),
  );
  final container = ProviderScope.containerOf(tester.element(find.byType(UltronApp)));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 500));
  return (container: container, tokens: tokens);
}

class _NoFiles implements FileSource {
  const _NoFiles();
  @override
  Future<PickedFile?> pick() async => null;
}
