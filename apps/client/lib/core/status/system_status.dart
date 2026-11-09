import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_exception.dart';
import '../api/models.dart';
import '../auth/session.dart';
import '../providers.dart';

/// Connection to the backend as shown in the sidebar and dashboard.
enum BackendLink { checking, online, degraded, offline }

class SystemStatus {
  const SystemStatus({
    this.link = BackendLink.checking,
    this.live,
    this.ready,
    this.ai,
    this.error,
    this.checkedAt,
  });

  final BackendLink link;
  final HealthLive? live;
  final HealthReady? ready;
  final AiStatus? ai;
  final String? error;
  final DateTime? checkedAt;

  bool get cloudAvailable => ai?.cloudAvailable ?? false;
  bool get localAvailable => ai?.localAiAvailable ?? false;
  ProviderStatus? get localProvider => ai?.providers.where((p) => p.isLocal && p.configured).firstOrNull;
}

final systemStatusProvider = NotifierProvider<SystemStatusController, SystemStatus>(SystemStatusController.new);

/// Polls health and AI status while signed in (every 20 s, or on demand).
class SystemStatusController extends Notifier<SystemStatus> {
  static const interval = Duration(seconds: 20);
  Timer? _timer;
  bool _busy = false;

  @override
  SystemStatus build() {
    final signedIn = ref.watch(sessionProvider) is SignedIn;
    ref.watch(apiProvider);
    _timer?.cancel();
    ref.onDispose(() => _timer?.cancel());
    if (signedIn) {
      _timer = Timer.periodic(interval, (_) => refresh());
      Future.microtask(refresh);
    }
    return const SystemStatus();
  }

  Future<void> refresh() async {
    if (_busy) return;
    _busy = true;
    final api = ref.read(apiProvider);
    try {
      final live = await api.healthLive();
      final ready = await api.healthReady();
      AiStatus? ai;
      try {
        ai = await api.aiStatus();
      } on ApiException catch (e) {
        if (e.isUnauthorized) ref.read(sessionProvider.notifier).sessionExpired();
      }
      state = SystemStatus(
        link: ready.ready ? BackendLink.online : BackendLink.degraded,
        live: live,
        ready: ready,
        ai: ai,
        checkedAt: DateTime.now(),
      );
    } on ApiException catch (e) {
      state = SystemStatus(link: BackendLink.offline, error: e.message, checkedAt: DateTime.now());
    } finally {
      _busy = false;
    }
  }
}
