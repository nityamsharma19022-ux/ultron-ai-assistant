/// Models for the Command Center: operating modes, notifications, device
/// metrics and conversation search.
library;

DateTime _date(Object? v) => DateTime.tryParse(v as String? ?? '')?.toLocal() ?? DateTime.now();

class AssistantModeInfo {
  const AssistantModeInfo({
    required this.key,
    required this.name,
    this.personality = '',
    this.aiMode,
    this.memory = true,
    this.toolAreas = const ['core', 'pc', 'phone'],
    this.quiet = false,
    this.builtin = true,
    this.active = false,
  });
  factory AssistantModeInfo.fromJson(Map<String, dynamic> j) => AssistantModeInfo(
    key: j['key'] as String,
    name: j['name'] as String? ?? j['key'] as String,
    personality: j['personality'] as String? ?? '',
    aiMode: j['ai_mode'] as String?,
    memory: j['memory'] as bool? ?? true,
    toolAreas: [for (final a in (j['tool_areas'] as List? ?? const [])) a as String],
    quiet: j['quiet'] as bool? ?? false,
    builtin: j['builtin'] as bool? ?? true,
    active: j['active'] as bool? ?? false,
  );
  final String key;
  final String name;
  final String personality;
  final String? aiMode;
  final bool memory;
  final List<String> toolAreas;
  final bool quiet;
  final bool builtin;
  final bool active;
}

class NotificationItem {
  const NotificationItem({
    required this.id,
    required this.kind,
    required this.title,
    required this.body,
    required this.priority,
    required this.read,
    required this.announce,
    required this.createdAt,
    this.taskId,
  });
  factory NotificationItem.fromJson(Map<String, dynamic> j) => NotificationItem(
    id: j['id'] as String,
    kind: j['kind'] as String? ?? '',
    title: j['title'] as String? ?? '',
    body: j['body'] as String? ?? '',
    priority: j['priority'] as String? ?? 'normal',
    read: j['read'] as bool? ?? false,
    announce: j['announce'] as bool? ?? false,
    taskId: j['task_id'] as String?,
    createdAt: _date(j['created_at']),
  );
  final String id;
  final String kind;
  final String title;
  final String body;
  final String priority;
  final bool read;
  final bool announce;
  final String? taskId;
  final DateTime createdAt;

  bool get urgent => priority == 'urgent' || priority == 'high';
}

class NotificationSettingsInfo {
  const NotificationSettingsInfo({
    this.quietStart,
    this.quietEnd,
    this.utcOffsetMinutes = 0,
    this.minPriority = 'normal',
    this.dailyBriefing,
  });
  factory NotificationSettingsInfo.fromJson(Map<String, dynamic> j) => NotificationSettingsInfo(
    quietStart: j['quiet_start'] as String?,
    quietEnd: j['quiet_end'] as String?,
    utcOffsetMinutes: j['utc_offset_minutes'] as int? ?? 0,
    minPriority: j['min_priority'] as String? ?? 'normal',
    dailyBriefing: j['daily_briefing'] as String?,
  );
  final String? quietStart;
  final String? quietEnd;
  final int utcOffsetMinutes;
  final String minPriority;
  final String? dailyBriefing;

  Map<String, dynamic> toJson() => {
    'quiet_start': quietStart,
    'quiet_end': quietEnd,
    'utc_offset_minutes': utcOffsetMinutes,
    'min_priority': minPriority,
    'daily_briefing': dailyBriefing,
  };
}

class DeviceMetrics {
  const DeviceMetrics({
    required this.deviceId,
    required this.deviceName,
    required this.platform,
    required this.values,
    this.updatedAt,
  });
  factory DeviceMetrics.fromJson(Map<String, dynamic> j) => DeviceMetrics(
    deviceId: j['device_id'] as String,
    deviceName: j['device_name'] as String? ?? '',
    platform: j['platform'] as String? ?? '',
    values: (j['metrics'] as Map?)?.cast<String, dynamic>() ?? const {},
    updatedAt: j['updated_at'] == null ? null : _date(j['updated_at']),
  );
  final String deviceId;
  final String deviceName;
  final String platform;
  final Map<String, dynamic> values;
  final DateTime? updatedAt;

  double? _num(String key) => (values[key] as num?)?.toDouble();
  double? get cpu => _num('cpu_percent');
  double? get memory => _num('memory_percent');
  double? get battery => _num('battery_percent');
  double? get diskFreeGb => _num('disk_free_gb');
  bool? get charging => values['charging'] as bool?;
  String? get network => values['network'] as String?;
}

class SearchHit {
  const SearchHit({
    required this.conversationId,
    required this.messageId,
    required this.role,
    required this.snippet,
    required this.createdAt,
    this.conversationTitle,
    this.isPrivate = false,
    this.project,
  });
  factory SearchHit.fromJson(Map<String, dynamic> j) => SearchHit(
    conversationId: j['conversation_id'] as String,
    conversationTitle: j['conversation_title'] as String?,
    isPrivate: j['is_private'] as bool? ?? false,
    project: j['project'] as String?,
    messageId: j['message_id'] as String,
    role: j['role'] as String? ?? 'user',
    snippet: j['snippet'] as String? ?? '',
    createdAt: _date(j['created_at']),
  );
  final String conversationId;
  final String? conversationTitle;
  final bool isPrivate;
  final String? project;
  final String messageId;
  final String role;

  /// Matching words are wrapped in « and ».
  final String snippet;
  final DateTime createdAt;
}

/// Result of sending one tiny test message to an AI provider through Core.
class ProviderTestResult {
  const ProviderTestResult({
    required this.provider,
    required this.ok,
    required this.seconds,
    this.model,
    this.reply,
    this.error,
  });
  factory ProviderTestResult.fromJson(Map<String, dynamic> j) => ProviderTestResult(
    provider: j['provider'] as String,
    ok: j['ok'] as bool? ?? false,
    seconds: (j['seconds'] as num?)?.toDouble() ?? 0,
    model: j['model'] as String?,
    reply: j['reply'] as String?,
    error: j['error'] as String?,
  );
  final String provider;
  final bool ok;
  final double seconds;
  final String? model;
  final String? reply;
  final String? error;
}

class UsageRow {
  const UsageRow({
    required this.provider,
    required this.replies,
    this.kind,
    this.model,
    this.failed = 0,
    this.fallbacks = 0,
    this.inputTokens = 0,
    this.outputTokens = 0,
    this.avgFirstTokenMs,
    this.avgDurationMs,
  });
  factory UsageRow.fromJson(Map<String, dynamic> j) => UsageRow(
    avgFirstTokenMs: j['avg_first_token_ms'] as int?,
    avgDurationMs: j['avg_duration_ms'] as int?,
    provider: j['provider'] as String,
    kind: j['kind'] as String?,
    model: j['model'] as String?,
    replies: j['replies'] as int? ?? 0,
    failed: j['failed'] as int? ?? 0,
    fallbacks: j['fallbacks'] as int? ?? 0,
    inputTokens: j['input_tokens'] as int? ?? 0,
    outputTokens: j['output_tokens'] as int? ?? 0,
  );
  final String provider;
  final String? kind;
  final String? model;
  final int replies;
  final int failed;
  final int fallbacks;
  final int inputTokens;
  final int outputTokens;

  /// Measured by Core: average time to the first word / to the end.
  final int? avgFirstTokenMs;
  final int? avgDurationMs;
}

class UsageInfo {
  const UsageInfo({required this.days, required this.totalReplies, required this.rows});
  factory UsageInfo.fromJson(Map<String, dynamic> j) => UsageInfo(
    days: j['days'] as int? ?? 7,
    totalReplies: j['total_replies'] as int? ?? 0,
    rows: [for (final r in (j['rows'] as List? ?? const [])) UsageRow.fromJson(r as Map<String, dynamic>)],
  );
  final int days;
  final int totalReplies;
  final List<UsageRow> rows;
}

/// Friendly names for AI providers.
String providerDisplayName(String name) => switch (name) {
  'freellmapi' => 'FreeLLMAPI',
  'groq' => 'Groq',
  'gemini' => 'Gemini',
  'openrouter' => 'OpenRouter',
  'anthropic' => 'Anthropic',
  'ollama' => 'Ollama (local)',
  'custom' => 'Custom',
  _ => name,
};
