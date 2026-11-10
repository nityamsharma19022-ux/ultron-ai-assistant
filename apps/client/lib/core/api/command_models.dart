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
