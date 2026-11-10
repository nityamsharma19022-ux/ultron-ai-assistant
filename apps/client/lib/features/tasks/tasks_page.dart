import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/task_models.dart';
import '../../core/providers.dart';
import '../../core/theme/ultron_colors.dart';
import '../../widgets/glass_panel.dart';
import '../voice/voice_controller.dart';
import 'tasks_controller.dart';

/// Tasks: tell ULTRON what to do, follow and control tasks, permissions
/// and the activity history.
class TasksPage extends ConsumerWidget {
  const TasksPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) => DefaultTabController(
    length: 3,
    child: Column(
      children: [
        const _AutomationBar(),
        const TabBar(
          tabs: [
            Tab(key: Key('tab-tasks'), text: 'Tasks'),
            Tab(key: Key('tab-permissions'), text: 'Permissions'),
            Tab(key: Key('tab-activity'), text: 'Activity'),
          ],
        ),
        const Expanded(child: TabBarView(children: [_TasksTab(), PermissionsTab(), ActivityTab()])),
      ],
    ),
  );
}

void _toast(BuildContext context, String text) => ScaffoldMessenger.of(context)
  ..hideCurrentSnackBar()
  ..showSnackBar(SnackBar(content: Text(text)));

Future<void> _guard(BuildContext context, Future<void> Function() action) async {
  try {
    await action();
  } on ApiException catch (e) {
    if (context.mounted) _toast(context, e.message);
  }
}

// ---------------------------------------------------------- automation bar

class _AutomationBar extends ConsumerWidget {
  const _AutomationBar();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auto = ref.watch(automationProvider).value;
    final controller = ref.read(automationProvider.notifier);
    final (label, color) = auto == null
        ? ('Checking…', UltronColors.textSecondary)
        : auto.stopped
        ? ('Emergency stop is on', UltronColors.danger)
        : !auto.enabled
        ? ('Automation is off', UltronColors.warning)
        : ('Automation on', UltronColors.success);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: Row(
        children: [
          Icon(Icons.circle, size: 10, color: color),
          const SizedBox(width: 8),
          Expanded(child: Text(label, key: const Key('automation-label'))),
          if (auto != null && auto.stopped)
            TextButton(
              key: const Key('clear-stop'),
              onPressed: () => _guard(context, controller.clearStop),
              child: const Text('Resume'),
            )
          else
            FilledButton.icon(
              key: const Key('emergency-stop'),
              style: FilledButton.styleFrom(backgroundColor: UltronColors.danger, foregroundColor: Colors.white),
              onPressed: () => _guard(context, () async {
                await controller.emergencyStop();
                if (context.mounted) _toast(context, 'Stopped. Nothing will run until you resume.');
              }),
              icon: const Icon(Icons.pan_tool_outlined, size: 18),
              label: const Text('STOP ALL'),
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- tasks tab

class _TasksTab extends ConsumerWidget {
  const _TasksTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tasks = ref.watch(tasksProvider);
    return RefreshIndicator(
      onRefresh: ref.read(tasksProvider.notifier).refresh,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
        children: [
          const CommandBar(),
          const SizedBox(height: 16),
          ...tasks.when(
            loading: () => [const LinearProgressIndicator(minHeight: 2)],
            error: (e, _) => [Text(e is ApiException ? e.message : 'Could not load tasks')],
            data: (list) => list.isEmpty
                ? [
                    const Padding(
                      padding: EdgeInsets.all(24),
                      child: Text(
                        'No tasks yet. Try "organize my downloads", "open VS Code" or '
                        '"remind me to stretch in 20 minutes".',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: UltronColors.textSecondary),
                      ),
                    ),
                  ]
                : [for (final t in list) TaskCard(task: t)],
          ),
        ],
      ),
    );
  }
}

/// "Tell ULTRON what to do": typed or spoken; runs a task or answers.
class CommandBar extends ConsumerStatefulWidget {
  const CommandBar({super.key});

  @override
  ConsumerState<CommandBar> createState() => _CommandBarState();
}

class _CommandBarState extends ConsumerState<CommandBar> {
  final _text = TextEditingController();
  bool _sending = false;
  String? _answer;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _submit([String? spoken]) async {
    final value = (spoken ?? _text.text).trim();
    if (value.isEmpty || _sending) return;
    setState(() {
      _sending = true;
      _answer = null;
    });
    try {
      final result = await ref.read(apiProvider).assistantCommand(value, source: spoken != null ? 'voice' : 'text');
      if (result.task != null) ref.read(tasksProvider.notifier).upsert(result.task!);
      _text.clear();
      if (mounted) setState(() => _answer = result.message);
    } on ApiException catch (e) {
      if (mounted) setState(() => _answer = e.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _speak() async {
    final heard = await ref.read(voiceProvider.notifier).capture();
    if (heard != null) await _submit(heard);
  }

  @override
  Widget build(BuildContext context) {
    final listening = ref.watch(voiceProvider.select((v) => v.listening));
    return GlassPanel(
      padding: const EdgeInsets.fromLTRB(14, 8, 8, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: TextField(
                  key: const Key('command-input'),
                  controller: _text,
                  enabled: !_sending,
                  onSubmitted: (_) => _submit(),
                  textInputAction: TextInputAction.send,
                  decoration: const InputDecoration(
                    hintText: 'Tell ULTRON what to do…',
                    border: InputBorder.none,
                    enabledBorder: InputBorder.none,
                    focusedBorder: InputBorder.none,
                    filled: false,
                  ),
                ),
              ),
              IconButton(
                key: const Key('command-mic'),
                tooltip: listening ? 'Listening…' : 'Speak',
                onPressed: _sending ? null : (listening ? ref.read(voiceProvider.notifier).finishCapture : _speak),
                icon: Icon(listening ? Icons.graphic_eq : Icons.mic_none),
              ),
              _sending
                  ? const Padding(
                      padding: EdgeInsets.all(12),
                      child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
                    )
                  : IconButton.filled(
                      key: const Key('command-send'),
                      tooltip: 'Do it',
                      onPressed: _submit,
                      icon: const Icon(Icons.bolt),
                    ),
            ],
          ),
          if (_answer != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(0, 4, 8, 6),
              child: SelectableText(_answer!, key: const Key('command-answer')),
            ),
        ],
      ),
    );
  }
}

Color statusColor(String status) => switch (status) {
  'completed' || 'succeeded' => UltronColors.success,
  'failed' => UltronColors.danger,
  'awaiting_approval' => UltronColors.warning,
  'running' || 'ready' || 'queued' => UltronColors.cloud,
  _ => UltronColors.textSecondary,
};

String statusLabel(String status) => switch (status) {
  'awaiting_approval' => 'Needs approval',
  'queued' => 'Queued',
  'running' => 'Running',
  'paused' => 'Paused',
  'completed' => 'Done',
  'failed' => 'Failed',
  'cancelled' => 'Cancelled',
  'planning' => 'Planning',
  _ => status,
};

IconData _targetIcon(String target) => switch (target) {
  'windows' => Icons.desktop_windows_outlined,
  'android' => Icons.phone_android,
  _ => Icons.hub_outlined,
};

IconData _stepIcon(String status) => switch (status) {
  'succeeded' => Icons.check_circle,
  'failed' => Icons.cancel,
  'running' => Icons.autorenew,
  'ready' => Icons.hourglass_top,
  'awaiting_approval' => Icons.help_outline,
  'cancelled' || 'skipped' => Icons.remove_circle_outline,
  _ => Icons.radio_button_unchecked,
};

class TaskCard extends ConsumerWidget {
  const TaskCard({super.key, required this.task});
  final TaskInfo task;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = ref.read(tasksProvider.notifier);
    final color = statusColor(task.status);
    final routine = task.waitingSteps.isNotEmpty && task.waitingSteps.every((s) => s.risk == 'A');
    return Padding(
      key: Key('task-${task.id}'),
      padding: const EdgeInsets.only(bottom: 12),
      child: GlassPanel(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(task.title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: color.withValues(alpha: 0.5)),
                  ),
                  child: Text(
                    statusLabel(task.status),
                    key: Key('task-status-${task.id}'),
                    style: TextStyle(color: color, fontSize: 11.5, fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
            if (task.request != task.title)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  '"${task.request}"',
                  style: const TextStyle(color: UltronColors.textMuted, fontSize: 12.5, fontStyle: FontStyle.italic),
                ),
              ),
            const SizedBox(height: 10),
            for (final s in task.steps)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(_stepIcon(s.status), size: 17, color: statusColor(s.status)),
                    const SizedBox(width: 8),
                    Icon(_targetIcon(s.target), size: 15, color: UltronColors.textMuted),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(s.title, style: const TextStyle(fontSize: 13.5)),
                          if (s.risk != 'A')
                            const Text(
                              'Important change: always asks',
                              style: TextStyle(fontSize: 11.5, color: UltronColors.warning),
                            ),
                          if ((s.error ?? s.summary ?? s.progress) case final note?)
                            Text(
                              note,
                              style: TextStyle(
                                fontSize: 12,
                                color: s.error != null ? UltronColors.danger : UltronColors.textSecondary,
                              ),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                if (task.needsApproval) ...[
                  FilledButton(
                    key: Key('approve-${task.id}'),
                    onPressed: () => _guard(context, () => c.approve(task.id)),
                    child: const Text('Approve'),
                  ),
                  if (routine)
                    OutlinedButton(
                      key: Key('always-${task.id}'),
                      onPressed: () => _guard(context, () => c.approve(task.id, remember: true)),
                      child: const Text('Always allow'),
                    ),
                  TextButton(
                    key: Key('reject-${task.id}'),
                    onPressed: () => _guard(context, () => c.control(task.id, 'reject')),
                    child: const Text('Reject'),
                  ),
                ],
                if (task.status == 'queued' || task.status == 'running')
                  TextButton(
                    key: Key('pause-${task.id}'),
                    onPressed: () => _guard(context, () => c.control(task.id, 'pause')),
                    child: const Text('Pause'),
                  ),
                if (task.status == 'paused')
                  TextButton(
                    key: Key('resume-${task.id}'),
                    onPressed: () => _guard(context, () => c.control(task.id, 'resume')),
                    child: const Text('Resume'),
                  ),
                if (!task.isFinished && !task.needsApproval)
                  TextButton(
                    key: Key('cancel-${task.id}'),
                    onPressed: () => _guard(context, () => c.control(task.id, 'cancel')),
                    child: const Text('Cancel'),
                  ),
                if (task.status == 'failed' || task.status == 'cancelled')
                  TextButton(
                    key: Key('retry-${task.id}'),
                    onPressed: () => _guard(context, () => c.control(task.id, 'retry')),
                    child: const Text('Retry'),
                  ),
                if (task.status == 'completed' && !task.isPrivate)
                  PopupMenuButton<String>(
                    key: Key('repeat-${task.id}'),
                    tooltip: 'Repeat',
                    onSelected: (every) => _guard(context, () async {
                      await ref.read(apiProvider).repeatTask(task.id, every: every);
                      if (context.mounted) _toast(context, 'This task now repeats $every.');
                    }),
                    itemBuilder: (_) => const [
                      PopupMenuItem(value: 'hourly', child: Text('Repeat every hour')),
                      PopupMenuItem(value: 'daily', child: Text('Repeat every day')),
                      PopupMenuItem(value: 'weekly', child: Text('Repeat every week')),
                    ],
                    child: const Padding(
                      padding: EdgeInsets.symmetric(horizontal: 8, vertical: 10),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [Icon(Icons.repeat, size: 18), SizedBox(width: 6), Text('Repeat')],
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------- permissions tab

class PermissionsTab extends ConsumerWidget {
  const PermissionsTab({super.key});

  static const _areas = {'core': 'ULTRON Core', 'pc': 'Your PC', 'phone': 'Your phone'};

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final perms = ref.watch(permissionsProvider);
    final auto = ref.watch(automationProvider).value;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        GlassPanel(
          child: SwitchListTile(
            key: const Key('automation-switch'),
            contentPadding: EdgeInsets.zero,
            value: auto?.enabled ?? true,
            onChanged: (v) => _guard(context, () => ref.read(automationProvider.notifier).setEnabled(v)),
            title: const Text('Run tasks automatically'),
            subtitle: const Text(
              'Master switch. When off, tasks wait until you turn it back on.',
              style: TextStyle(fontSize: 12.5),
            ),
          ),
        ),
        const SizedBox(height: 12),
        const Text(
          'Routine actions you allow here run without asking. Important changes (overwriting, '
          'deleting) and anything external always ask.',
          style: TextStyle(color: UltronColors.textSecondary, fontSize: 12.5),
        ),
        const SizedBox(height: 12),
        ...perms.when(
          loading: () => [const LinearProgressIndicator(minHeight: 2)],
          error: (e, _) => [Text(e is ApiException ? e.message : 'Could not load permissions')],
          data: (list) => [
            for (final area in _areas.entries)
              if (list.any((p) => p.area == area.key))
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: GlassPanel(
                    padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(area.value.toUpperCase(), style: Theme.of(context).textTheme.labelLarge),
                        for (final p in list.where((p) => p.area == area.key))
                          SwitchListTile(
                            key: Key('perm-${p.scope}'),
                            contentPadding: EdgeInsets.zero,
                            dense: true,
                            value: p.granted,
                            onChanged: p.alwaysAsks
                                ? null
                                : (v) => _guard(context, () => ref.read(permissionsProvider.notifier).set(p.scope, v)),
                            title: Text(p.title),
                            subtitle: p.alwaysAsks
                                ? const Text('Always asks', style: TextStyle(color: UltronColors.warning))
                                : p.expiresAt != null
                                ? Text('Until ${p.expiresAt!.toString().substring(0, 16)}')
                                : null,
                          ),
                      ],
                    ),
                  ),
                ),
          ],
        ),
      ],
    );
  }
}

// ------------------------------------------------------------- activity tab

class ActivityTab extends ConsumerWidget {
  const ActivityTab({super.key});

  static IconData icon(String kind) => switch (kind.split('.').first) {
    'task' || 'step' => Icons.bolt,
    'memory' => Icons.psychology_outlined,
    'permission' => Icons.verified_user_outlined,
    'automation' => Icons.pan_tool_outlined,
    'schedule' => Icons.repeat,
    _ => Icons.history,
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(activityProvider);
    return RefreshIndicator(
      onRefresh: () => ref.refresh(activityProvider.future),
      child: items.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ListView(children: [Text(e is ApiException ? e.message : 'Could not load activity')]),
        data: (list) => list.isEmpty
            ? ListView(
                children: const [
                  Padding(
                    padding: EdgeInsets.all(24),
                    child: Text('Nothing yet.', textAlign: TextAlign.center),
                  ),
                ],
              )
            : ListView.builder(
                key: const Key('activity-list'),
                padding: const EdgeInsets.fromLTRB(8, 8, 8, 24),
                itemCount: list.length + 1,
                itemBuilder: (context, i) {
                  if (i == list.length) {
                    return TextButton(
                      onPressed: () => _guard(context, ref.read(activityProvider.notifier).loadMore),
                      child: const Text('Load older'),
                    );
                  }
                  final a = list[i];
                  final failed = a.kind.endsWith('failed') || a.kind.contains('emergency');
                  return ListTile(
                    dense: true,
                    leading: Icon(icon(a.kind), color: failed ? UltronColors.danger : UltronColors.textSecondary),
                    title: Text(a.summary),
                    subtitle: Text(
                      '${a.createdAt.toString().substring(0, 16)} · ${a.kind}',
                      style: const TextStyle(fontSize: 11.5, color: UltronColors.textMuted),
                    ),
                  );
                },
              ),
      ),
    );
  }
}
