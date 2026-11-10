// Models for tasks, permissions, memory, activity, agents and reminders.

DateTime _date(Object? v) => DateTime.tryParse(v as String? ?? '')?.toLocal() ?? DateTime.now();
DateTime? _dateOrNull(Object? v) => v == null ? null : DateTime.tryParse(v as String)?.toLocal();
Map<String, dynamic> _map(Object? v) => (v as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{};

const terminalTaskStatuses = {'completed', 'failed', 'cancelled'};

class TaskStepInfo {
  const TaskStepInfo({
    required this.id,
    required this.idx,
    required this.tool,
    required this.title,
    required this.target,
    required this.risk,
    required this.scope,
    required this.status,
    this.attempts = 0,
    this.result = const {},
    this.error,
    this.progress,
  });
  factory TaskStepInfo.fromJson(Map<String, dynamic> j) => TaskStepInfo(
    id: j['id'] as String,
    idx: j['idx'] as int? ?? 0,
    tool: j['tool'] as String,
    title: j['title'] as String? ?? j['tool'] as String,
    target: j['target'] as String? ?? 'core',
    risk: j['risk'] as String? ?? 'A',
    scope: j['scope'] as String? ?? '',
    status: j['status'] as String,
    attempts: j['attempts'] as int? ?? 0,
    result: _map(j['result']),
    error: j['error'] as String?,
    progress: j['progress'] as String?,
  );
  final String id;
  final int idx;
  final String tool;
  final String title;
  final String target; // core | windows | android
  final String risk; // A | B | C
  final String scope;
  final String status;
  final int attempts;
  final Map<String, dynamic> result;
  final String? error;
  final String? progress;

  String? get summary => result['summary'] as String?;
}

class TaskInfo {
  const TaskInfo({
    required this.id,
    required this.title,
    required this.request,
    required this.status,
    required this.steps,
    required this.createdAt,
    this.planSource = 'manual',
    this.isPrivate = false,
    this.summary,
    this.error,
    this.scheduleId,
  });
  factory TaskInfo.fromJson(Map<String, dynamic> j) => TaskInfo(
    id: j['id'] as String,
    title: j['title'] as String? ?? '',
    request: j['request'] as String? ?? '',
    status: j['status'] as String,
    planSource: j['plan_source'] as String? ?? 'manual',
    isPrivate: j['is_private'] as bool? ?? false,
    summary: j['summary'] as String?,
    error: j['error'] as String?,
    scheduleId: j['schedule_id'] as String?,
    createdAt: _date(j['created_at']),
    steps: [for (final s in (j['steps'] as List? ?? const [])) TaskStepInfo.fromJson(s as Map<String, dynamic>)],
  );
  final String id;
  final String title;
  final String request;
  final String status;
  final String planSource;
  final bool isPrivate;
  final String? summary;
  final String? error;
  final String? scheduleId;
  final DateTime createdAt;
  final List<TaskStepInfo> steps;

  bool get isFinished => terminalTaskStatuses.contains(status);
  bool get needsApproval => status == 'awaiting_approval';
  Iterable<TaskStepInfo> get waitingSteps => steps.where((s) => s.status == 'awaiting_approval');
}

/// What /assistant/command returned: a task, or a direct answer.
class CommandResult {
  const CommandResult({required this.type, required this.message, this.task});
  factory CommandResult.fromJson(Map<String, dynamic> j) => CommandResult(
    type: j['type'] as String? ?? 'answer',
    message: j['message'] as String? ?? '',
    task: j['task'] == null ? null : TaskInfo.fromJson(j['task'] as Map<String, dynamic>),
  );
  final String type;
  final String message;
  final TaskInfo? task;
  bool get isTask => type == 'task';
}

class PermissionInfo {
  const PermissionInfo({
    required this.scope,
    required this.title,
    required this.granted,
    required this.alwaysAsks,
    this.expiresAt,
    this.tools = const [],
  });
  factory PermissionInfo.fromJson(Map<String, dynamic> j) => PermissionInfo(
    scope: j['scope'] as String,
    title: j['title'] as String? ?? j['scope'] as String,
    granted: j['granted'] as bool? ?? false,
    alwaysAsks: j['always_asks'] as bool? ?? false,
    expiresAt: _dateOrNull(j['expires_at']),
    tools: [for (final t in (j['tools'] as List? ?? const [])) t as String],
  );
  final String scope;
  final String title;
  final bool granted;
  final bool alwaysAsks;
  final DateTime? expiresAt;
  final List<String> tools;

  /// "pc", "phone" or "core" (memory, AI writing, reminders).
  String get area => scope.startsWith('pc.')
      ? 'pc'
      : scope.startsWith('phone.')
      ? 'phone'
      : 'core';
}

class AutomationInfo {
  const AutomationInfo({required this.enabled, required this.stopped});
  factory AutomationInfo.fromJson(Map<String, dynamic> j) =>
      AutomationInfo(enabled: j['enabled'] as bool? ?? true, stopped: j['stopped'] as bool? ?? false);
  final bool enabled;
  final bool stopped;
  bool get running => enabled && !stopped;
}

class MemoryItem {
  const MemoryItem({
    required this.id,
    required this.content,
    required this.kind,
    required this.source,
    required this.isPrivate,
    required this.pinned,
    required this.updatedAt,
    this.lastUsedAt,
  });
  factory MemoryItem.fromJson(Map<String, dynamic> j) => MemoryItem(
    id: j['id'] as String,
    content: j['content'] as String,
    kind: j['kind'] as String? ?? 'note',
    source: j['source'] as String? ?? 'user',
    isPrivate: j['is_private'] as bool? ?? false,
    pinned: j['pinned'] as bool? ?? false,
    updatedAt: _date(j['updated_at']),
    lastUsedAt: _dateOrNull(j['last_used_at']),
  );
  final String id;
  final String content;
  final String kind;
  final String source;
  final bool isPrivate;
  final bool pinned;
  final DateTime updatedAt;
  final DateTime? lastUsedAt;
}

class ActivityItem {
  const ActivityItem({
    required this.seq,
    required this.kind,
    required this.summary,
    required this.createdAt,
    this.taskId,
  });
  factory ActivityItem.fromJson(Map<String, dynamic> j) => ActivityItem(
    seq: j['seq'] as int,
    kind: j['kind'] as String,
    summary: j['summary'] as String? ?? '',
    taskId: j['task_id'] as String?,
    createdAt: _date(j['created_at']),
  );
  final int seq;
  final String kind;
  final String summary;
  final String? taskId;
  final DateTime createdAt;
}

class AgentStatus {
  const AgentStatus({
    required this.deviceId,
    required this.deviceName,
    required this.target,
    required this.online,
    required this.lastSeenAt,
    this.tools = const [],
    this.capabilities = const {},
    this.version,
  });
  factory AgentStatus.fromJson(Map<String, dynamic> j) => AgentStatus(
    deviceId: j['device_id'] as String,
    deviceName: j['device_name'] as String? ?? '',
    target: j['target'] as String? ?? '',
    online: j['online'] as bool? ?? false,
    lastSeenAt: _date(j['last_seen_at']),
    version: j['agent_version'] as String?,
    tools: [for (final t in (j['tools'] as List? ?? const [])) t as String],
    capabilities: {
      for (final e in _map(j['capabilities']).entries) e.key: [for (final v in (e.value as List? ?? const [])) '$v'],
    },
  );
  final String deviceId;
  final String deviceName;
  final String target;
  final bool online;
  final DateTime lastSeenAt;
  final String? version;
  final List<String> tools;
  final Map<String, List<String>> capabilities;
}

/// A step handed to this device by the agent protocol.
class StepWork {
  const StepWork({required this.id, required this.tool, required this.args, required this.title});
  factory StepWork.fromJson(Map<String, dynamic> j) => StepWork(
    id: j['id'] as String,
    tool: j['tool'] as String,
    args: _map(j['args']),
    title: j['title'] as String? ?? '',
  );
  final String id;
  final String tool;
  final Map<String, dynamic> args;
  final String title;
}

class ReminderItem {
  const ReminderItem({required this.id, required this.text, required this.dueAt, this.done = false});
  factory ReminderItem.fromJson(Map<String, dynamic> j) => ReminderItem(
    id: j['id'] as String,
    text: j['text'] as String? ?? '',
    dueAt: _date(j['due_at']),
    done: j['done'] as bool? ?? false,
  );
  final String id;
  final String text;
  final DateTime dueAt;
  final bool done;
}

class DocumentInfo {
  const DocumentInfo({
    required this.id,
    required this.name,
    required this.kind,
    required this.size,
    required this.chunkCount,
    required this.isPrivate,
    required this.createdAt,
    this.pages,
    this.reused = false,
  });
  factory DocumentInfo.fromJson(Map<String, dynamic> j) => DocumentInfo(
    id: j['id'] as String,
    name: j['name'] as String? ?? 'document',
    kind: j['kind'] as String? ?? 'text',
    size: j['size'] as int? ?? 0,
    pages: j['pages'] as int?,
    chunkCount: j['chunk_count'] as int? ?? 0,
    isPrivate: j['is_private'] as bool? ?? false,
    reused: j['reused'] as bool? ?? false,
    createdAt: _date(j['created_at']),
  );
  final String id;
  final String name;
  final String kind; // pdf | docx | sheet | text
  final int size;
  final int? pages;
  final int chunkCount;
  final bool isPrivate;
  final bool reused;
  final DateTime createdAt;

  String get sizeLabel => size >= 1 << 20
      ? '${(size / (1 << 20)).toStringAsFixed(1)} MB'
      : size >= 1024
      ? '${(size / 1024).toStringAsFixed(0)} KB'
      : '$size B';
}
