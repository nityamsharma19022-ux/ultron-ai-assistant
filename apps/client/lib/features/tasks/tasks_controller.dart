import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/task_models.dart';
import '../../core/auth/session.dart';
import '../../core/providers.dart';

/// Recent tasks; refreshes every few seconds while any are still running.
final tasksProvider = AsyncNotifierProvider<TasksController, List<TaskInfo>>(TasksController.new);

class TasksController extends AsyncNotifier<List<TaskInfo>> {
  Timer? _poll;
  Duration pollEvery = const Duration(seconds: 3);

  @override
  Future<List<TaskInfo>> build() async {
    ref.onDispose(() => _poll?.cancel());
    if (ref.watch(sessionProvider) is! SignedIn) return const [];
    final tasks = await ref.watch(apiProvider).tasks();
    _schedule(tasks);
    return tasks;
  }

  void _schedule(List<TaskInfo> tasks) {
    _poll?.cancel();
    if (tasks.any((t) => !t.isFinished)) _poll = Timer(pollEvery, refresh);
  }

  Future<void> refresh() async {
    try {
      final tasks = await ref.read(apiProvider).tasks();
      state = AsyncData(tasks);
      _schedule(tasks);
    } on ApiException catch (e, st) {
      if (!state.hasValue) state = AsyncError(e, st);
    }
  }

  void upsert(TaskInfo task) {
    final list = [...state.value ?? const <TaskInfo>[]];
    final i = list.indexWhere((t) => t.id == task.id);
    if (i >= 0) {
      list[i] = task;
    } else {
      list.insert(0, task);
    }
    state = AsyncData(list);
    _schedule(list);
  }

  Future<void> approve(String id, {bool remember = false}) async {
    upsert(await ref.read(apiProvider).approveTask(id, remember: remember));
    if (remember) ref.invalidate(permissionsProvider);
  }

  Future<void> control(String id, String action) async => upsert(await ref.read(apiProvider).controlTask(id, action));
}

final automationProvider = AsyncNotifierProvider<AutomationController, AutomationInfo>(AutomationController.new);

class AutomationController extends AsyncNotifier<AutomationInfo> {
  @override
  Future<AutomationInfo> build() async {
    if (ref.watch(sessionProvider) is! SignedIn) return const AutomationInfo(enabled: true, stopped: false);
    return ref.watch(apiProvider).automation();
  }

  Future<void> setEnabled(bool enabled) async =>
      state = AsyncData(await ref.read(apiProvider).setAutomation(enabled: enabled));

  /// Autonomy level 0-5 for an area ("core", "pc", "phone").
  Future<void> setLevel(String area, int level) async =>
      state = AsyncData(await ref.read(apiProvider).setAutomation(levels: {area: level}));

  Future<void> clearStop() async => state = AsyncData(await ref.read(apiProvider).setAutomation(stopped: false));

  Future<void> emergencyStop() async {
    state = AsyncData(await ref.read(apiProvider).emergencyStop());
    await ref.read(tasksProvider.notifier).refresh();
  }
}

final permissionsProvider = AsyncNotifierProvider<PermissionsController, List<PermissionInfo>>(
  PermissionsController.new,
);

class PermissionsController extends AsyncNotifier<List<PermissionInfo>> {
  @override
  Future<List<PermissionInfo>> build() async {
    if (ref.watch(sessionProvider) is! SignedIn) return const [];
    return ref.watch(apiProvider).permissions();
  }

  Future<void> set(String scope, bool enabled) async {
    final updated = await ref.read(apiProvider).setPermission(scope, enabled: enabled);
    state = AsyncData([for (final p in state.value ?? const <PermissionInfo>[]) p.scope == scope ? updated : p]);
  }
}

final activityProvider = AsyncNotifierProvider<ActivityController, List<ActivityItem>>(ActivityController.new);

class ActivityController extends AsyncNotifier<List<ActivityItem>> {
  @override
  Future<List<ActivityItem>> build() async {
    if (ref.watch(sessionProvider) is! SignedIn) return const [];
    return ref.watch(apiProvider).activity(limit: 50);
  }

  Future<void> loadMore() async {
    final current = state.value ?? const <ActivityItem>[];
    if (current.isEmpty) return;
    final more = await ref.read(apiProvider).activity(limit: 50, beforeSeq: current.last.seq);
    state = AsyncData([...current, ...more]);
  }
}
