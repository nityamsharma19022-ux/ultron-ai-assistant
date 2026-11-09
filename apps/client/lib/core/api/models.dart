// Data returned by the ULTRON Core API (see apps/core).

DateTime _date(Object? v) => DateTime.tryParse(v as String? ?? '')?.toLocal() ?? DateTime.now();

class UserInfo {
  const UserInfo({required this.id, required this.email, this.displayName, this.isOwner = false});
  factory UserInfo.fromJson(Map<String, dynamic> j) => UserInfo(
    id: j['id'] as String,
    email: j['email'] as String,
    displayName: j['display_name'] as String?,
    isOwner: j['is_owner'] as bool? ?? false,
  );
  final String id;
  final String email;
  final String? displayName;
  final bool isOwner;

  String get name => (displayName?.isNotEmpty ?? false) ? displayName! : email.split('@').first;
}

class DeviceInfo {
  const DeviceInfo({
    required this.id,
    required this.name,
    required this.platform,
    required this.createdAt,
    this.lastSeenAt,
    this.revokedAt,
  });
  factory DeviceInfo.fromJson(Map<String, dynamic> j) => DeviceInfo(
    id: j['id'] as String,
    name: j['name'] as String,
    platform: j['platform'] as String,
    createdAt: _date(j['created_at']),
    lastSeenAt: j['last_seen_at'] == null ? null : _date(j['last_seen_at']),
    revokedAt: j['revoked_at'] == null ? null : _date(j['revoked_at']),
  );
  final String id;
  final String name;
  final String platform;
  final DateTime createdAt;
  final DateTime? lastSeenAt;
  final DateTime? revokedAt;
  bool get isRevoked => revokedAt != null;
}

class Me {
  const Me(this.user, this.device);
  factory Me.fromJson(Map<String, dynamic> j) => Me(
    UserInfo.fromJson(j['user'] as Map<String, dynamic>),
    DeviceInfo.fromJson(j['device'] as Map<String, dynamic>),
  );
  final UserInfo user;
  final DeviceInfo device;
}

class TokenPair {
  const TokenPair({required this.accessToken, required this.refreshToken, required this.deviceId});
  factory TokenPair.fromJson(Map<String, dynamic> j) => TokenPair(
    accessToken: j['access_token'] as String,
    refreshToken: j['refresh_token'] as String,
    deviceId: j['device_id'] as String,
  );
  final String accessToken;
  final String refreshToken;
  final String deviceId;
}

class Conversation {
  const Conversation({
    required this.id,
    required this.title,
    required this.isPrivate,
    required this.createdAt,
    required this.updatedAt,
  });
  factory Conversation.fromJson(Map<String, dynamic> j) => Conversation(
    id: j['id'] as String,
    title: j['title'] as String?,
    isPrivate: j['is_private'] as bool? ?? false,
    createdAt: _date(j['created_at']),
    updatedAt: _date(j['updated_at']),
  );
  final String id;
  final String? title;
  final bool isPrivate;
  final DateTime createdAt;
  final DateTime updatedAt;

  String get displayTitle => (title?.isNotEmpty ?? false) ? title! : 'New conversation';
}

/// Message status as stored by the backend.
enum MessageStatus { streaming, complete, incomplete, failed, cancelled }

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.role,
    required this.content,
    required this.status,
    this.provider,
    this.providerKind,
    this.model,
    this.fallbackUsed = false,
    this.errorCode,
    this.errorMessage,
    this.timestamp,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> j) => ChatMessage(
    id: j['id'] as String,
    role: j['role'] as String,
    content: j['content'] as String? ?? '',
    status: MessageStatus.values.firstWhere(
      (s) => s.name == j['status'],
      orElse: () => MessageStatus.complete,
    ),
    provider: j['provider'] as String?,
    providerKind: j['provider_kind'] as String?,
    model: j['model'] as String?,
    fallbackUsed: j['fallback_used'] as bool? ?? false,
    errorCode: j['error_code'] as String?,
    timestamp: _date(j['created_at']),
  );

  final String id;
  final String role;
  final String content;
  final MessageStatus status;
  final String? provider;
  final String? providerKind;
  final String? model;
  final bool fallbackUsed;
  final String? errorCode;
  final String? errorMessage;
  final DateTime? timestamp;

  DateTime get createdAt => timestamp ?? DateTime.now();
  bool get isUser => role == 'user';
  bool get isLocal => providerKind == 'local';

  ChatMessage copyWith({
    String? content,
    MessageStatus? status,
    String? provider,
    String? providerKind,
    String? model,
    bool? fallbackUsed,
    String? errorCode,
    String? errorMessage,
  }) => ChatMessage(
    id: id,
    role: role,
    content: content ?? this.content,
    status: status ?? this.status,
    provider: provider ?? this.provider,
    providerKind: providerKind ?? this.providerKind,
    model: model ?? this.model,
    fallbackUsed: fallbackUsed ?? this.fallbackUsed,
    errorCode: errorCode ?? this.errorCode,
    errorMessage: errorMessage ?? this.errorMessage,
    timestamp: timestamp,
  );
}

class ProviderStatus {
  const ProviderStatus({
    required this.name,
    required this.kind,
    required this.configured,
    required this.available,
    required this.status,
    this.model,
    this.reason,
    this.cooldownRemainingSeconds,
    this.modelLoaded,
  });
  factory ProviderStatus.fromJson(Map<String, dynamic> j) => ProviderStatus(
    name: j['name'] as String,
    kind: j['kind'] as String,
    model: j['model'] as String?,
    configured: j['configured'] as bool? ?? false,
    available: j['available'] as bool? ?? false,
    status: j['status'] as String? ?? 'unknown',
    reason: j['reason'] as String?,
    cooldownRemainingSeconds: j['cooldown_remaining_seconds'] as int?,
    modelLoaded: j['model_loaded'] as bool?,
  );
  final String name;
  final String kind;
  final String? model;
  final bool configured;
  final bool available;
  final String status;
  final String? reason;
  final int? cooldownRemainingSeconds;
  final bool? modelLoaded;
  bool get isLocal => kind == 'local';
}

class AiStatus {
  const AiStatus({
    required this.mode,
    required this.cloudAvailable,
    required this.localAiAvailable,
    required this.privateConversationsSupported,
    required this.providers,
  });
  factory AiStatus.fromJson(Map<String, dynamic> j) => AiStatus(
    mode: j['mode'] as String? ?? 'auto',
    cloudAvailable: j['cloud_available'] as bool? ?? false,
    localAiAvailable: j['local_ai_available'] as bool? ?? false,
    privateConversationsSupported: j['private_conversations_supported'] as bool? ?? false,
    providers: [
      for (final p in (j['providers'] as List? ?? const [])) ProviderStatus.fromJson(p as Map<String, dynamic>),
    ],
  );
  final String mode;
  final bool cloudAvailable;
  final bool localAiAvailable;
  final bool privateConversationsSupported;
  final List<ProviderStatus> providers;
}

class AiPreferences {
  const AiPreferences({
    required this.mode,
    required this.cloudOrder,
    required this.privateByDefault,
    required this.availableCloudProviders,
  });
  factory AiPreferences.fromJson(Map<String, dynamic> j) => AiPreferences(
    mode: j['mode'] as String? ?? 'auto',
    cloudOrder: [for (final n in (j['cloud_order'] as List? ?? const [])) n as String],
    privateByDefault: j['private_by_default'] as bool? ?? false,
    availableCloudProviders: [
      for (final n in (j['available_cloud_providers'] as List? ?? const [])) n as String,
    ],
  );
  final String mode;
  final List<String> cloudOrder;
  final bool privateByDefault;
  final List<String> availableCloudProviders;

  Map<String, dynamic> toJson() => {
    'mode': mode,
    'cloud_order': cloudOrder,
    'private_by_default': privateByDefault,
  };

  AiPreferences copyWith({String? mode, List<String>? cloudOrder, bool? privateByDefault}) => AiPreferences(
    mode: mode ?? this.mode,
    cloudOrder: cloudOrder ?? this.cloudOrder,
    privateByDefault: privateByDefault ?? this.privateByDefault,
    availableCloudProviders: availableCloudProviders,
  );
}

class HealthLive {
  const HealthLive({required this.service, required this.version, required this.deployment, required this.nodeId});
  factory HealthLive.fromJson(Map<String, dynamic> j) => HealthLive(
    service: j['service'] as String? ?? '',
    version: j['version'] as String? ?? '',
    deployment: j['deployment'] as String? ?? '',
    nodeId: j['node_id'] as String? ?? '',
  );
  final String service;
  final String version;
  final String deployment;
  final String nodeId;
}

class HealthReady {
  const HealthReady({required this.ready, required this.dbMode, required this.checks});
  factory HealthReady.fromJson(Map<String, dynamic> j) => HealthReady(
    ready: j['status'] == 'ready',
    dbMode: j['db_mode'] as String? ?? '',
    checks: (j['checks'] as Map?)?.cast<String, dynamic>() ?? const {},
  );
  final bool ready;
  final String dbMode;
  final Map<String, dynamic> checks;

  String checkStatus(String name) => ((checks[name] as Map?)?['status'] as String?) ?? 'unknown';
}

class WarmupResult {
  const WarmupResult({required this.model, required this.alreadyLoaded, required this.seconds});
  factory WarmupResult.fromJson(Map<String, dynamic> j) => WarmupResult(
    model: j['model'] as String?,
    alreadyLoaded: j['already_loaded'] as bool? ?? false,
    seconds: (j['seconds'] as num?)?.toDouble() ?? 0,
  );
  final String? model;
  final bool alreadyLoaded;
  final double seconds;
}
