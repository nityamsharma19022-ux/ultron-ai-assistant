import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/command_models.dart';
import '../../core/api/task_models.dart';
import '../../core/auth/session.dart';
import '../../core/notices.dart';
import '../../core/providers.dart';

/// Operating modes (Normal, Work, Developer, Study, Focus, custom).
final modesProvider = AsyncNotifierProvider<ModesController, List<AssistantModeInfo>>(ModesController.new);

class ModesController extends AsyncNotifier<List<AssistantModeInfo>> {
  @override
  Future<List<AssistantModeInfo>> build() async {
    if (ref.watch(sessionProvider) is! SignedIn) return const [];
    return ref.watch(apiProvider).modes();
  }

  Future<void> activate(String key) async {
    await ref.read(apiProvider).setActiveMode(key);
    state = AsyncData(await ref.read(apiProvider).modes());
  }

  Future<void> create({required String name, String personality = '', bool quiet = false}) async {
    await ref.read(apiProvider).createMode(name: name, personality: personality, quiet: quiet);
    state = AsyncData(await ref.read(apiProvider).modes());
  }

  Future<void> remove(String key) async {
    await ref.read(apiProvider).deleteMode(key);
    state = AsyncData(await ref.read(apiProvider).modes());
  }
}

final activeModeProvider = Provider<AssistantModeInfo?>(
  (ref) => ref.watch(modesProvider).value?.where((m) => m.active).firstOrNull,
);

/// ULTRON's notifications, checked every [pollEvery] while signed in. New
/// ones that should be announced (priority, quiet hours, mode) appear as an
/// in-app message.
final notificationsProvider = AsyncNotifierProvider<NotificationsController, List<NotificationItem>>(
  NotificationsController.new,
);

class NotificationsController extends AsyncNotifier<List<NotificationItem>> {
  static Duration pollEvery = const Duration(seconds: 30);
  Timer? _timer;
  final _seen = <String>{};

  @override
  Future<List<NotificationItem>> build() async {
    _timer?.cancel();
    ref.onDispose(() => _timer?.cancel());
    if (ref.watch(sessionProvider) is! SignedIn) return const [];
    final items = await ref.watch(apiProvider).notifications();
    _seen.addAll(items.map((n) => n.id)); // don't announce what was already there
    _timer = Timer.periodic(pollEvery, (_) => refresh());
    return items;
  }

  Future<void> refresh() async {
    try {
      final items = await ref.read(apiProvider).notifications();
      for (final n in items.reversed) {
        if (_seen.add(n.id) && !n.read && n.announce) {
          ref.read(noticesProvider.notifier).show('🔔 ${n.title}');
        }
      }
      state = AsyncData(items);
    } on ApiException {
      // Next round.
    }
  }

  Future<void> markRead(String id) async {
    await ref.read(apiProvider).markNotificationRead(id);
    state = AsyncData([for (final n in state.value ?? const <NotificationItem>[]) n.id == id ? _copyRead(n) : n]);
  }

  Future<void> markAllRead() async {
    await ref.read(apiProvider).markAllNotificationsRead();
    state = AsyncData([for (final n in state.value ?? const <NotificationItem>[]) _copyRead(n)]);
  }

  static NotificationItem _copyRead(NotificationItem n) => NotificationItem(
    id: n.id,
    kind: n.kind,
    title: n.title,
    body: n.body,
    priority: n.priority,
    read: true,
    announce: false,
    taskId: n.taskId,
    createdAt: n.createdAt,
  );
}

final unreadCountProvider = Provider<int>(
  (ref) => ref.watch(notificationsProvider).value?.where((n) => !n.read).length ?? 0,
);

/// Live CPU / memory / battery of your devices (sent by the Windows agent
/// and the phone app), refreshed every [pollEvery].
final metricsProvider = AsyncNotifierProvider<MetricsController, List<DeviceMetrics>>(MetricsController.new);

class MetricsController extends AsyncNotifier<List<DeviceMetrics>> {
  static Duration pollEvery = const Duration(seconds: 30);
  Timer? _timer;

  @override
  Future<List<DeviceMetrics>> build() async {
    _timer?.cancel();
    ref.onDispose(() => _timer?.cancel());
    if (ref.watch(sessionProvider) is! SignedIn) return const [];
    final items = await ref.watch(apiProvider).deviceMetrics();
    _timer = Timer.periodic(pollEvery, (_) => refresh());
    return items;
  }

  Future<void> refresh() async {
    try {
      state = AsyncData(await ref.read(apiProvider).deviceMetrics());
    } on ApiException {
      // Keep the last values.
    }
  }
}

/// Upcoming reminders for the Command Center.
final upcomingRemindersProvider = FutureProvider<List<ReminderItem>>((ref) async {
  if (ref.watch(sessionProvider) is! SignedIn) return const [];
  final all = await ref.watch(apiProvider).reminders();
  return [
    for (final r in all)
      if (!r.done) r,
  ]..sort((a, b) => a.dueAt.compareTo(b.dueAt));
});
