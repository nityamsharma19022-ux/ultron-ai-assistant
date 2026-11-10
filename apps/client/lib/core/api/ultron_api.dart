import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../auth/token_store.dart';
import 'api_exception.dart';
import 'idle_timeout.dart';
import 'models.dart';
import 'sse.dart';
import 'task_models.dart';

/// Events of a streamed reply (mirrors the backend's SSE events).
sealed class ChatStreamEvent {
  const ChatStreamEvent();
}

class StreamCreated extends ChatStreamEvent {
  const StreamCreated(this.userMessage, this.assistantMessageId, this.isPrivate);
  final ChatMessage userMessage;
  final String assistantMessageId;
  final bool isPrivate;
}

/// Progress: routing -> waiting / loading_model -> generating.
class StreamStatus extends ChatStreamEvent {
  const StreamStatus(this.phase, {this.provider, this.kind, this.model, this.modelLoaded});
  final String phase;
  final String? provider;
  final String? kind;
  final String? model;
  final bool? modelLoaded;
}

class StreamProviderSelected extends ChatStreamEvent {
  const StreamProviderSelected({required this.provider, required this.kind, this.model, this.fallbackUsed = false});
  final String provider;
  final String kind;
  final String? model;
  final bool fallbackUsed;
}

class StreamDelta extends ChatStreamEvent {
  const StreamDelta(this.text);
  final String text;
}

class StreamCompleted extends ChatStreamEvent {
  const StreamCompleted(this.assistantMessage);
  final ChatMessage assistantMessage;
}

class StreamCancelled extends ChatStreamEvent {
  const StreamCancelled(this.assistantMessage);
  final ChatMessage assistantMessage;
}

class StreamFailed extends ChatStreamEvent {
  const StreamFailed(this.code, this.message, [this.assistantMessage]);
  final String code;
  final String message;
  final ChatMessage? assistantMessage;
}

/// Client for ULTRON Core. Holds no secrets of its own: tokens come from
/// [TokenStore] and are refreshed automatically when they expire.
class UltronApi {
  UltronApi({
    required String baseUrl,
    required this.tokens,
    http.Client? client,
    this.requestTimeout = const Duration(seconds: 20),
    this.streamIdleTimeout = const Duration(seconds: 60),
  }) : baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), ''),
       _client = client ?? http.Client();

  final String baseUrl;
  final TokenStore tokens;
  final Duration requestTimeout;

  /// Longest silence allowed while streaming (the server sends keep-alives
  /// every ~10 s, so silence means the connection is gone).
  final Duration streamIdleTimeout;
  final http.Client _client;
  Future<bool>? _refreshing;

  void close() => _client.close();

  Uri _uri(String path, [Map<String, String>? query]) => Uri.parse('$baseUrl$path').replace(queryParameters: query);

  // ------------------------------------------------------------ health

  Future<HealthLive> healthLive() async =>
      HealthLive.fromJson(await _json('GET', '/health/live', auth: false, timeout: const Duration(seconds: 6)));

  /// Readiness is returned even when the server answers 503 (not ready).
  Future<HealthReady> healthReady() async {
    try {
      final r = await _client.get(_uri('/health/ready')).timeout(const Duration(seconds: 8));
      return HealthReady.fromJson(jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>);
    } on TimeoutException {
      throw const ApiException.network();
    } on http.ClientException {
      throw const ApiException.network();
    } on FormatException {
      throw const ApiException('Unexpected answer from the server', code: 'bad_response');
    }
  }

  // -------------------------------------------------------------- auth

  Future<TokenPair> login({
    required String email,
    required String password,
    required String deviceName,
    required String platform,
  }) async {
    final deviceId = await tokens.readDeviceId();
    final body = await _json(
      'POST',
      '/api/v1/auth/login',
      auth: false,
      body: {
        'email': email.trim(),
        'password': password,
        'device_name': deviceName,
        'platform': platform,
        'device_id': ?deviceId,
      },
    );
    final pair = TokenPair.fromJson(body);
    await tokens.save(pair);
    return pair;
  }

  Future<void> logout() async {
    try {
      await _json('POST', '/api/v1/auth/logout', expectBody: false);
    } on ApiException {
      // Signing out locally must always work, even offline.
    } finally {
      await tokens.clear();
    }
  }

  Future<Me> me() async => Me.fromJson(await _json('GET', '/api/v1/auth/me'));

  Future<List<DeviceInfo>> devices() async => [
    for (final d in await _json('GET', '/api/v1/devices') as List) DeviceInfo.fromJson(d as Map<String, dynamic>),
  ];

  Future<void> revokeDevice(String id) => _json('DELETE', '/api/v1/devices/$id', expectBody: false);

  // ---------------------------------------------------------------- AI

  Future<AiStatus> aiStatus() async => AiStatus.fromJson(await _json('GET', '/api/v1/ai/status'));

  Future<AiPreferences> aiPreferences() async => AiPreferences.fromJson(await _json('GET', '/api/v1/ai/preferences'));

  Future<AiPreferences> saveAiPreferences(AiPreferences p) async =>
      AiPreferences.fromJson(await _json('PUT', '/api/v1/ai/preferences', body: p.toJson()));

  Future<WarmupResult> warmupLocalModel() async =>
      WarmupResult.fromJson(await _json('POST', '/api/v1/ai/local/warmup', timeout: const Duration(minutes: 4)));

  // ------------------------------------------------- assistant and tasks

  /// One entry point for commands and questions (typed or spoken).
  Future<CommandResult> assistantCommand(
    String text, {
    bool wait = false,
    bool private = false,
    String source = 'text',
    String? timezone,
  }) async => CommandResult.fromJson(
    await _json(
      'POST',
      '/api/v1/assistant/command',
      body: {
        'text': text,
        'wait': wait,
        'private': private,
        'source': source,
        'timezone': ?timezone,
        'utc_offset_minutes': DateTime.now().timeZoneOffset.inMinutes,
      },
      timeout: const Duration(seconds: 90),
    ),
  );

  Future<List<TaskInfo>> tasks({String? status, int limit = 50}) async => [
    for (final t in await _json('GET', '/api/v1/tasks', query: {'limit': '$limit', 'status': ?status}) as List)
      TaskInfo.fromJson(t as Map<String, dynamic>),
  ];

  Future<TaskInfo> task(String id) async => TaskInfo.fromJson(await _json('GET', '/api/v1/tasks/$id'));

  Future<TaskInfo> approveTask(String id, {bool remember = false}) async =>
      TaskInfo.fromJson(await _json('POST', '/api/v1/tasks/$id/approve', body: {'remember': remember}));

  /// cancel | reject | pause | resume | retry
  Future<TaskInfo> controlTask(String id, String action) async =>
      TaskInfo.fromJson(await _json('POST', '/api/v1/tasks/$id/$action'));

  Future<void> repeatTask(String id, {required String every, String? at, String? timezone}) =>
      _json('POST', '/api/v1/tasks/$id/repeat', body: {'every': every, 'at': ?at, 'timezone': ?timezone});

  Future<List<PermissionInfo>> permissions() async => [
    for (final p in await _json('GET', '/api/v1/permissions') as List)
      PermissionInfo.fromJson(p as Map<String, dynamic>),
  ];

  Future<PermissionInfo> setPermission(String scope, {required bool enabled, int? expiresInDays}) async =>
      PermissionInfo.fromJson(
        await _json('PUT', '/api/v1/permissions/$scope', body: {'enabled': enabled, 'expires_in_days': ?expiresInDays}),
      );

  Future<AutomationInfo> automation() async => AutomationInfo.fromJson(await _json('GET', '/api/v1/automation'));

  Future<AutomationInfo> setAutomation({bool? enabled, bool? stopped}) async => AutomationInfo.fromJson(
    await _json('PUT', '/api/v1/automation', body: {'enabled': ?enabled, 'stopped': ?stopped}),
  );

  Future<AutomationInfo> emergencyStop() async =>
      AutomationInfo.fromJson(await _json('POST', '/api/v1/automation/emergency-stop'));

  Future<List<ActivityItem>> activity({int limit = 50, int? beforeSeq}) async => [
    for (final a in await _json(
      'GET',
      '/api/v1/activity',
      query: {'limit': '$limit', 'before_seq': ?beforeSeq?.toString()},
    ) as List)
      ActivityItem.fromJson(a as Map<String, dynamic>),
  ];

  Future<List<ReminderItem>> reminders({bool due = false}) async => [
    for (final r in await _json('GET', '/api/v1/reminders', query: {'due': '$due'}) as List)
      ReminderItem.fromJson(r as Map<String, dynamic>),
  ];

  Future<void> markReminder(String id, {bool? done, bool? delivered}) =>
      _json('PATCH', '/api/v1/reminders/$id', body: {'done': ?done, 'delivered': ?delivered});

  // ------------------------------------------------------------ memory

  Future<List<MemoryItem>> memories({String? query, int limit = 200}) async => [
    for (final m in await _json('GET', '/api/v1/memories', query: {'limit': '$limit', 'q': ?query}) as List)
      MemoryItem.fromJson(m as Map<String, dynamic>),
  ];

  Future<MemoryItem> createMemory(
    String content, {
    String kind = 'note',
    bool pinned = false,
    bool private = false,
  }) async => MemoryItem.fromJson(
    await _json(
      'POST',
      '/api/v1/memories',
      body: {'content': content, 'kind': kind, 'pinned': pinned, 'is_private': private},
    ),
  );

  Future<MemoryItem> updateMemory(String id, {String? content, String? kind, bool? pinned, bool? private}) async =>
      MemoryItem.fromJson(
        await _json(
          'PATCH',
          '/api/v1/memories/$id',
          body: {'content': ?content, 'kind': ?kind, 'pinned': ?pinned, 'is_private': ?private},
        ),
      );

  Future<void> deleteMemory(String id) => _json('DELETE', '/api/v1/memories/$id', expectBody: false);

  Future<Map<String, dynamic>> exportMemories() async =>
      (await _json('GET', '/api/v1/memories/export') as Map).cast<String, dynamic>();

  Future<void> deleteAllMemories() => _json('DELETE', '/api/v1/memories', query: {'confirm': 'delete-all'});

  // ------------------------------------------------------------ agents

  Future<List<AgentStatus>> agents() async => [
    for (final a in await _json('GET', '/api/v1/agents') as List) AgentStatus.fromJson(a as Map<String, dynamic>),
  ];

  Future<void> agentHello(List<String> tools, {Map<String, List<String>> capabilities = const {}, String? version}) =>
      _json('POST', '/api/v1/agents/hello', body: {'tools': tools, 'capabilities': capabilities, 'version': ?version});

  /// Long poll; null when there is no work.
  Future<StepWork?> nextStep({int wait = 20}) async {
    final j = await _json(
      'GET',
      '/api/v1/agents/steps/next',
      query: {'wait': '$wait'},
      timeout: Duration(seconds: wait + 15),
    );
    return j == null ? null : StepWork.fromJson(j as Map<String, dynamic>);
  }

  Future<void> stepResult(String stepId, {required bool ok, Map<String, dynamic>? result, String? error}) => _json(
    'POST',
    '/api/v1/agents/steps/$stepId/result',
    body: {'ok': ok, 'result': result ?? <String, dynamic>{}, 'error': ?error},
  );

  // ------------------------------------------------------------ chat

  Future<List<Conversation>> conversations({int limit = 100}) async => [
    for (final c in await _json('GET', '/api/v1/conversations', query: {'limit': '$limit'}) as List)
      Conversation.fromJson(c as Map<String, dynamic>),
  ];

  Future<Conversation> createConversation({bool? isPrivate, String? title}) async => Conversation.fromJson(
    await _json('POST', '/api/v1/conversations', body: {'is_private': ?isPrivate, 'title': ?title}),
  );

  Future<(Conversation, List<ChatMessage>)> conversation(String id) async {
    final j = await _json('GET', '/api/v1/conversations/$id', query: {'limit': '200'}) as Map<String, dynamic>;
    return (
      Conversation.fromJson(j['conversation'] as Map<String, dynamic>),
      [for (final m in j['messages'] as List) ChatMessage.fromJson(m as Map<String, dynamic>)],
    );
  }

  Future<Conversation> updateConversation(String id, {String? title, bool makePrivate = false}) async =>
      Conversation.fromJson(
        await _json('PATCH', '/api/v1/conversations/$id', body: {'title': ?title, if (makePrivate) 'is_private': true}),
      );

  Future<void> deleteConversation(String id) => _json('DELETE', '/api/v1/conversations/$id', expectBody: false);

  Future<void> cancelReply(String conversationId) => _json('POST', '/api/v1/conversations/$conversationId/cancel');

  /// Sends a message and streams the reply. Cancelling the subscription (or
  /// completing [abort]) closes the connection; the server then stops.
  Stream<ChatStreamEvent> sendMessage(String conversationId, String content, {Future<void>? abort}) async* {
    final response = await _sendStreaming(
      _uri('/api/v1/conversations/$conversationId/messages'),
      jsonEncode({'content': content, 'stream': true}),
      abort,
    );
    final bytes = withIdleTimeout<List<int>>(
      response.stream,
      streamIdleTimeout,
      () => const ApiException('The connection to ULTRON was lost.', code: 'stream_stalled'),
    );
    try {
      await for (final e in parseSse(bytes)) {
        final event = _toChatEvent(e);
        if (event != null) yield event;
      }
    } on http.RequestAbortedException {
      return;
    } on http.ClientException {
      throw const ApiException('The connection to ULTRON was lost.', code: 'stream_stalled');
    }
  }

  Future<http.StreamedResponse> _sendStreaming(Uri uri, String body, Future<void>? abort, {bool retry = true}) async {
    final request = http.AbortableRequest('POST', uri, abortTrigger: abort)
      ..headers.addAll(await _headers())
      ..headers['Accept'] = 'text/event-stream'
      ..body = body;
    final http.StreamedResponse response;
    try {
      response = await _client.send(request).timeout(requestTimeout);
    } on TimeoutException {
      throw const ApiException.network();
    } on http.RequestAbortedException {
      throw const ApiException('Cancelled', code: 'cancelled');
    } on http.ClientException {
      throw const ApiException.network();
    }
    if (response.statusCode == 401 && retry && await _refresh()) {
      await response.stream.drain<void>();
      return _sendStreaming(uri, body, abort, retry: false);
    }
    if (response.statusCode != 200) {
      final text = await response.stream.bytesToString();
      throw _error(response.statusCode, text);
    }
    return response;
  }

  static ChatStreamEvent? _toChatEvent(SseEvent e) {
    final d = e.json;
    ChatMessage? assistant() =>
        d['assistant_message'] == null ? null : ChatMessage.fromJson(d['assistant_message'] as Map<String, dynamic>);
    return switch (e.event) {
      'message.created' => StreamCreated(
        ChatMessage.fromJson(d['user_message'] as Map<String, dynamic>),
        d['assistant_message_id'] as String,
        d['private'] as bool? ?? false,
      ),
      'status' => StreamStatus(
        d['phase'] as String,
        provider: d['provider'] as String?,
        kind: d['kind'] as String?,
        model: d['model'] as String?,
        modelLoaded: d['model_loaded'] as bool?,
      ),
      'provider.selected' => StreamProviderSelected(
        provider: d['provider'] as String,
        kind: d['kind'] as String,
        model: d['model'] as String?,
        fallbackUsed: d['fallback_used'] as bool? ?? false,
      ),
      'delta' => StreamDelta(d['text'] as String),
      'message.completed' => StreamCompleted(assistant()!),
      'message.cancelled' => StreamCancelled(assistant()!),
      'error' => StreamFailed(
        d['code'] as String? ?? 'error',
        d['message'] as String? ?? 'Something went wrong.',
        assistant(),
      ),
      _ => null,
    };
  }

  // ---------------------------------------------------------- plumbing

  Future<Map<String, String>> _headers({bool auth = true}) async {
    final h = {'Content-Type': 'application/json'};
    if (auth) {
      final t = await tokens.read();
      if (t != null) h['Authorization'] = 'Bearer ${t.accessToken}';
    }
    return h;
  }

  Future<dynamic> _json(
    String method,
    String path, {
    Object? body,
    Map<String, String>? query,
    bool auth = true,
    bool expectBody = true,
    Duration? timeout,
    bool retry = true,
  }) async {
    final request = http.Request(method, _uri(path, query))..headers.addAll(await _headers(auth: auth));
    if (body != null) request.body = jsonEncode(body);
    final http.Response response;
    try {
      response = await http.Response.fromStream(await _client.send(request)).timeout(timeout ?? requestTimeout);
    } on TimeoutException {
      throw const ApiException.network('The ULTRON backend did not answer in time.');
    } on http.ClientException {
      throw const ApiException.network();
    }
    if (response.statusCode == 401 && auth && retry && await _refresh()) {
      return _json(method, path, body: body, query: query, expectBody: expectBody, timeout: timeout, retry: false);
    }
    final text = utf8.decode(response.bodyBytes);
    if (response.statusCode >= 400) throw _error(response.statusCode, text);
    if (!expectBody || text.isEmpty) return null;
    return jsonDecode(text);
  }

  /// Exchanges the refresh token for a new pair (only one refresh at a time).
  Future<bool> _refresh() => _refreshing ??= _doRefresh().whenComplete(() => _refreshing = null);

  Future<bool> _doRefresh() async {
    final current = await tokens.read();
    if (current == null) return false;
    try {
      final r = await _client
          .post(
            _uri('/api/v1/auth/refresh'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'refresh_token': current.refreshToken}),
          )
          .timeout(requestTimeout);
      if (r.statusCode != 200) {
        await tokens.clear();
        return false;
      }
      await tokens.save(TokenPair.fromJson(jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>));
      return true;
    } on TimeoutException {
      return false;
    } on http.ClientException {
      return false;
    }
  }

  static ApiException _error(int status, String text) {
    String? code;
    var message = 'Request failed (HTTP $status)';
    try {
      final detail = (jsonDecode(text) as Map<String, dynamic>)['detail'];
      if (detail is String) {
        message = detail;
      } else if (detail is Map) {
        code = detail['code'] as String?;
        message = detail['message'] as String? ?? message;
      } else if (detail is List && detail.isNotEmpty) {
        message = (detail.first as Map)['msg'] as String? ?? message;
        code = 'invalid_request';
      }
    } on FormatException {
      // Not JSON: keep the generic message.
    } on TypeError {
      // Unexpected shape: keep the generic message.
    }
    if (status == 401) {
      code ??= 'unauthorized';
      if (message == 'Not authenticated') message = 'Your session has ended. Please sign in again.';
    }
    if (status == 429) code ??= 'rate_limited';
    return ApiException(message, statusCode: status, code: code);
  }
}
