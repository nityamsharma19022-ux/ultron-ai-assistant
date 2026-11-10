import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/command_models.dart';
import '../../core/auth/session.dart';
import '../../core/notices.dart';
import '../../core/providers.dart';
import '../../core/settings/app_settings.dart';
import '../../core/theme/ultron_colors.dart';
import '../../widgets/glass_panel.dart';
import '../shell/sections.dart';
import '../tasks/tasks_controller.dart';
import '../tasks/tasks_page.dart' show CommandBar;
import 'command_controller.dart';

/// How the Command Center arranges its panels.
enum CommandLayout { grid, floating }

const _kLayout = 'command_layout';
String _posKey(String id) => 'command_panel_$id';

/// Quick commands shown under the command bar.
const quickCommands = [
  ('How is my PC doing', Icons.memory),
  ('Organize my downloads', Icons.folder_copy_outlined),
  ('Check my phone', Icons.smartphone),
  ('Open VS Code', Icons.code),
];

/// ULTRON's home: the clock, the active mode, the command bar and live
/// panels (devices, tasks, reminders, notifications, AI activity, autonomy).
/// On wide screens the panels can float and be dragged anywhere.
class CommandCenterPage extends ConsumerStatefulWidget {
  const CommandCenterPage({super.key});

  @override
  ConsumerState<CommandCenterPage> createState() => _CommandCenterPageState();
}

class _CommandCenterPageState extends ConsumerState<CommandCenterPage> {
  late CommandLayout _layout;
  final _positions = <String, Offset>{};

  @override
  void initState() {
    super.initState();
    final prefs = ref.read(sharedPreferencesProvider);
    _layout = prefs.getString(_kLayout) == 'floating' ? CommandLayout.floating : CommandLayout.grid;
    for (final id in _panelIds) {
      final raw = prefs.getString(_posKey(id))?.split(',');
      if (raw != null && raw.length == 2) {
        final x = double.tryParse(raw[0]), y = double.tryParse(raw[1]);
        if (x != null && y != null) _positions[id] = Offset(x, y);
      }
    }
  }

  static const _panelIds = ['devices', 'tasks', 'reminders', 'notifications', 'activity', 'autonomy'];

  Future<void> _setLayout(CommandLayout layout) async {
    setState(() => _layout = layout);
    await ref.read(sharedPreferencesProvider).setString(_kLayout, layout.name);
  }

  Future<void> _savePosition(String id) async {
    final p = _positions[id];
    if (p == null) return;
    await ref.read(sharedPreferencesProvider).setString(_posKey(id), '${p.dx.round()},${p.dy.round()}');
  }

  Future<void> _resetPositions() async {
    final prefs = ref.read(sharedPreferencesProvider);
    for (final id in _panelIds) {
      await prefs.remove(_posKey(id));
    }
    setState(_positions.clear);
  }

  List<_PanelSpec> get _panels => const [
    _PanelSpec('devices', 'Devices', Icons.devices_other, _DevicesPanel()),
    _PanelSpec('tasks', 'Tasks', Icons.bolt, _TasksPanel()),
    _PanelSpec('reminders', 'Reminders', Icons.alarm, _RemindersPanel()),
    _PanelSpec('notifications', 'Notifications', Icons.notifications_none, _NotificationsPanel()),
    _PanelSpec('activity', 'AI activity', Icons.auto_awesome, _ActivityPanel()),
    _PanelSpec('autonomy', 'Autonomy', Icons.tune, _AutonomyPanel()),
  ];

  @override
  Widget build(BuildContext context) {
    if (ref.watch(sessionProvider) is! SignedIn) return const SizedBox();
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 1000;
        final floating = wide && _layout == CommandLayout.floating;
        final header = Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Expanded(child: _Clock()),
                const _ModeChip(),
                if (wide) ...[
                  const SizedBox(width: 8),
                  SegmentedButton<CommandLayout>(
                    key: const Key('command-layout'),
                    showSelectedIcon: false,
                    segments: const [
                      ButtonSegment(value: CommandLayout.grid, icon: Icon(Icons.grid_view, size: 18), tooltip: 'Grid'),
                      ButtonSegment(
                        value: CommandLayout.floating,
                        icon: Icon(Icons.picture_in_picture_alt_outlined, size: 18),
                        tooltip: 'Floating panels',
                      ),
                    ],
                    selected: {_layout},
                    onSelectionChanged: (s) => _setLayout(s.first),
                  ),
                  if (floating)
                    IconButton(
                      key: const Key('reset-panels'),
                      tooltip: 'Reset panel positions',
                      onPressed: _resetPositions,
                      icon: const Icon(Icons.restart_alt),
                    ),
                ],
              ],
            ),
            const SizedBox(height: 16),
            const CommandBar(),
            const SizedBox(height: 10),
            const _QuickCommands(),
            const SizedBox(height: 18),
          ],
        );
        final pad = EdgeInsets.symmetric(horizontal: wide ? 28 : 14, vertical: 18);
        if (floating) {
          return Padding(
            padding: pad,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                header,
                Expanded(child: _floating(constraints.maxWidth - pad.horizontal)),
              ],
            ),
          );
        }
        final columns = constraints.maxWidth >= 1300
            ? 3
            : constraints.maxWidth >= 760
            ? 2
            : 1;
        final width = (constraints.maxWidth - pad.horizontal - (columns - 1) * 14) / columns;
        return ListView(
          key: const Key('command-center'),
          padding: pad,
          children: [
            header,
            Wrap(
              spacing: 14,
              runSpacing: 14,
              children: [
                for (final p in _panels)
                  SizedBox(
                    width: width,
                    child: _Panel(key: Key('panel-${p.id}'), spec: p),
                  ),
              ],
            ),
          ],
        );
      },
    );
  }

  Widget _floating(double width) => LayoutBuilder(
    key: const Key('command-center'),
    builder: (context, c) {
      const panelWidth = 340.0;
      final columns = math.max(1, (c.maxWidth / (panelWidth + 16)).floor());
      final panels = _panels;
      return Stack(
        clipBehavior: Clip.hardEdge,
        children: [
          for (var i = 0; i < panels.length; i++)
            Builder(
              builder: (context) {
                final p = panels[i];
                final fallback = Offset((i % columns) * (panelWidth + 16), (i ~/ columns) * 300.0);
                final pos = _positions[p.id] ?? fallback;
                final clamped = Offset(
                  pos.dx.clamp(0, math.max(0, c.maxWidth - panelWidth)),
                  pos.dy.clamp(0, math.max(0, c.maxHeight - 80)),
                );
                return Positioned(
                  left: clamped.dx,
                  top: clamped.dy,
                  width: panelWidth,
                  child: _Panel(
                    key: Key('panel-${p.id}'),
                    spec: p,
                    maxHeight: 360,
                    onDrag: (delta) => setState(() => _positions[p.id] = clamped + delta),
                    onDragEnd: () => _savePosition(p.id),
                  ),
                );
              },
            ),
        ],
      );
    },
  );
}

class _PanelSpec {
  const _PanelSpec(this.id, this.title, this.icon, this.child);
  final String id;
  final String title;
  final IconData icon;
  final Widget child;
}

class _Panel extends StatelessWidget {
  const _Panel({super.key, required this.spec, this.onDrag, this.onDragEnd, this.maxHeight});
  final _PanelSpec spec;
  final ValueChanged<Offset>? onDrag;
  final VoidCallback? onDragEnd;
  final double? maxHeight;

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    Widget title = Row(
      children: [
        Icon(spec.icon, size: 17, color: accent),
        const SizedBox(width: 9),
        Expanded(
          child: Text(spec.title, style: const TextStyle(fontWeight: FontWeight.w600, letterSpacing: 0.4)),
        ),
        if (onDrag != null) const Icon(Icons.drag_indicator, size: 18, color: UltronColors.textMuted),
      ],
    );
    if (onDrag != null) {
      title = MouseRegion(
        cursor: SystemMouseCursors.move,
        child: GestureDetector(
          key: Key('drag-${spec.id}'),
          behavior: HitTestBehavior.opaque,
          onPanUpdate: (d) => onDrag!(d.delta),
          onPanEnd: (_) => onDragEnd?.call(),
          child: title,
        ),
      );
    }
    final body = maxHeight == null
        ? spec.child
        : ConstrainedBox(
            constraints: BoxConstraints(maxHeight: maxHeight!),
            child: SingleChildScrollView(child: spec.child),
          );
    return GlassPanel(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [title, const SizedBox(height: 12), body],
      ),
    );
  }
}

// ------------------------------------------------------------------ header

class _Clock extends StatefulWidget {
  const _Clock();

  @override
  State<_Clock> createState() => _ClockState();
}

class _ClockState extends State<_Clock> {
  Timer? _timer;
  DateTime _now = DateTime.now();

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => setState(() => _now = DateTime.now()));
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  static const _days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  static const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  @override
  Widget build(BuildContext context) {
    final h = _now.hour, m = _now.minute.toString().padLeft(2, '0');
    final greeting = h < 5
        ? 'Working late'
        : h < 12
        ? 'Good morning'
        : h < 17
        ? 'Good afternoon'
        : 'Good evening';
    return Column(
      key: const Key('command-clock'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${h.toString().padLeft(2, '0')}:$m',
          style: TextStyle(
            fontSize: 40,
            fontWeight: FontWeight.w300,
            letterSpacing: 2,
            color: Theme.of(context).colorScheme.primary,
            height: 1,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          '$greeting · ${_days[_now.weekday - 1]}, ${_now.day} ${_months[_now.month - 1]}',
          style: const TextStyle(color: UltronColors.textSecondary),
        ),
      ],
    );
  }
}

class _ModeChip extends ConsumerWidget {
  const _ModeChip();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final modes = ref.watch(modesProvider).value ?? const <AssistantModeInfo>[];
    final active = ref.watch(activeModeProvider);
    if (modes.isEmpty) return const SizedBox();
    return PopupMenuButton<String>(
      key: const Key('mode-chip'),
      tooltip: 'Operating mode',
      onSelected: (key) async {
        try {
          await ref.read(modesProvider.notifier).activate(key);
        } on ApiException catch (e) {
          ref.read(noticesProvider.notifier).show(e.message);
        }
      },
      itemBuilder: (_) => [
        for (final m in modes)
          PopupMenuItem(
            key: Key('mode-${m.key}'),
            value: m.key,
            child: Row(
              children: [
                Icon(m.active ? Icons.radio_button_checked : Icons.radio_button_off, size: 18),
                const SizedBox(width: 10),
                Text(m.name),
                if (m.quiet) ...[
                  const SizedBox(width: 6),
                  const Icon(Icons.notifications_paused_outlined, size: 15, color: UltronColors.textMuted),
                ],
              ],
            ),
          ),
      ],
      child: Chip(avatar: const Icon(Icons.tune, size: 16), label: Text(active?.name ?? 'Normal assistant')),
    );
  }
}

class _QuickCommands extends ConsumerStatefulWidget {
  const _QuickCommands();

  @override
  ConsumerState<_QuickCommands> createState() => _QuickCommandsState();
}

class _QuickCommandsState extends ConsumerState<_QuickCommands> {
  String? _running;

  Future<void> _run(String text) async {
    setState(() => _running = text);
    try {
      final result = await ref.read(apiProvider).assistantCommand(text);
      if (result.task != null) ref.read(tasksProvider.notifier).upsert(result.task!);
      ref.read(noticesProvider.notifier).show(result.message);
    } on ApiException catch (e) {
      ref.read(noticesProvider.notifier).show(e.message);
    } finally {
      if (mounted) setState(() => _running = null);
    }
  }

  @override
  Widget build(BuildContext context) => Wrap(
    spacing: 8,
    runSpacing: 8,
    children: [
      for (final (text, icon) in quickCommands)
        ActionChip(
          key: Key('quick-${text.toLowerCase().replaceAll(' ', '-')}'),
          avatar: _running == text
              ? const SizedBox.square(dimension: 14, child: CircularProgressIndicator(strokeWidth: 2))
              : Icon(icon, size: 16),
          label: Text(text),
          onPressed: _running == null ? () => _run(text) : null,
        ),
    ],
  );
}

// ------------------------------------------------------------------ panels

class _Empty extends StatelessWidget {
  const _Empty(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Text(text, style: const TextStyle(color: UltronColors.textMuted, fontSize: 13)),
  );
}

Widget _loading(AsyncValue<Object?> v, Widget Function() data) => v.when(
  data: (_) => data(),
  loading: () => const Padding(padding: EdgeInsets.all(8), child: LinearProgressIndicator(minHeight: 2)),
  error: (e, _) => _Empty(e is ApiException ? e.message : 'Unavailable'),
);

String ago(DateTime t, [DateTime? now]) {
  final d = (now ?? DateTime.now()).difference(t);
  if (d.inSeconds < 60) return 'just now';
  if (d.inMinutes < 60) return '${d.inMinutes} min ago';
  if (d.inHours < 24) return '${d.inHours} h ago';
  return '${d.inDays} d ago';
}

String _when(DateTime t) {
  final now = DateTime.now();
  final hm = '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  if (t.year == now.year && t.month == now.month && t.day == now.day) return 'Today $hm';
  final tomorrow = now.add(const Duration(days: 1));
  if (t.year == tomorrow.year && t.month == tomorrow.month && t.day == tomorrow.day) return 'Tomorrow $hm';
  return '${t.day}/${t.month} $hm';
}

class _Meter extends StatelessWidget {
  const _Meter(this.label, this.value, {this.invert = false});
  final String label;
  final double value;

  /// Battery: low is bad.
  final bool invert;

  @override
  Widget build(BuildContext context) {
    final bad = invert ? value <= 15 : value >= 90;
    final warn = invert ? value <= 30 : value >= 75;
    final color = bad
        ? UltronColors.danger
        : warn
        ? UltronColors.warning
        : Theme.of(context).colorScheme.primary;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          SizedBox(
            width: 62,
            child: Text(label, style: const TextStyle(fontSize: 12, color: UltronColors.textSecondary)),
          ),
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(
                value: (value / 100).clamp(0, 1),
                minHeight: 6,
                color: color,
                backgroundColor: color.withValues(alpha: 0.12),
              ),
            ),
          ),
          SizedBox(
            width: 46,
            child: Text('${value.round()}%', textAlign: TextAlign.right, style: const TextStyle(fontSize: 12)),
          ),
        ],
      ),
    );
  }
}

class _DevicesPanel extends ConsumerWidget {
  const _DevicesPanel();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final metrics = ref.watch(metricsProvider);
    return _loading(metrics, () {
      final list = metrics.value!;
      if (list.isEmpty) {
        return const _Empty(
          'No live data yet. Start the Windows agent (uv run ultron-agent run) or open ULTRON on your phone.',
        );
      }
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final d in list)
            Padding(
              key: Key('metrics-${d.deviceId}'),
              padding: const EdgeInsets.only(bottom: 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Icon(d.platform == 'android' ? Icons.smartphone : Icons.computer, size: 16),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(d.deviceName, style: const TextStyle(fontWeight: FontWeight.w600)),
                      ),
                      if (d.updatedAt != null)
                        Text(ago(d.updatedAt!), style: const TextStyle(fontSize: 11, color: UltronColors.textMuted)),
                    ],
                  ),
                  const SizedBox(height: 4),
                  if (d.cpu != null) _Meter('CPU', d.cpu!),
                  if (d.memory != null) _Meter('Memory', d.memory!),
                  if (d.battery != null) _Meter(d.charging == true ? 'Battery ⚡' : 'Battery', d.battery!, invert: true),
                  if (d.diskFreeGb != null || d.network != null)
                    Text(
                      [
                        if (d.diskFreeGb != null) '${d.diskFreeGb!.toStringAsFixed(0)} GB free',
                        if (d.network != null) 'Network: ${d.network}',
                      ].join(' · '),
                      style: const TextStyle(fontSize: 12, color: UltronColors.textSecondary),
                    ),
                ],
              ),
            ),
        ],
      );
    });
  }
}

class _TasksPanel extends ConsumerWidget {
  const _TasksPanel();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tasks = ref.watch(tasksProvider);
    return _loading(tasks, () {
      final list = tasks.value!;
      final running = list.where((t) => !t.isFinished && !t.needsApproval).length;
      final waiting = list.where((t) => t.needsApproval).length;
      final failed = list.where((t) => t.status == 'failed').length;
      final active = [
        for (final t in list)
          if (!t.isFinished) t,
      ].take(4);
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              _Count('Running', running, Theme.of(context).colorScheme.primary),
              _Count('Need approval', waiting, UltronColors.warning),
              _Count('Failed', failed, UltronColors.danger),
            ],
          ),
          const SizedBox(height: 10),
          if (active.isEmpty) const _Empty('Nothing running.'),
          for (final t in active)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                children: [
                  Icon(t.needsApproval ? Icons.front_hand_outlined : Icons.sync, size: 15),
                  const SizedBox(width: 8),
                  Expanded(child: Text(t.title, maxLines: 1, overflow: TextOverflow.ellipsis)),
                ],
              ),
            ),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              key: const Key('open-tasks'),
              onPressed: () => ref.read(sectionProvider.notifier).select(AppSection.tasks),
              child: const Text('Open Tasks'),
            ),
          ),
        ],
      );
    });
  }
}

class _Count extends StatelessWidget {
  const _Count(this.label, this.value, this.color);
  final String label;
  final int value;
  final Color color;

  @override
  Widget build(BuildContext context) => Expanded(
    child: Column(
      children: [
        Text('$value', style: TextStyle(fontSize: 24, color: value > 0 ? color : UltronColors.textMuted)),
        Text(label, style: const TextStyle(fontSize: 11, color: UltronColors.textSecondary)),
      ],
    ),
  );
}

class _RemindersPanel extends ConsumerWidget {
  const _RemindersPanel();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final reminders = ref.watch(upcomingRemindersProvider);
    return _loading(reminders, () {
      final list = reminders.value!.take(5).toList();
      if (list.isEmpty) return const _Empty('No reminders. Try "remind me to stretch at 9 pm".');
      return Column(
        children: [
          for (final r in list)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.alarm, size: 18),
              title: Text(r.text, maxLines: 2, overflow: TextOverflow.ellipsis),
              trailing: Text(_when(r.dueAt), style: const TextStyle(fontSize: 12)),
            ),
        ],
      );
    });
  }
}

Color priorityColor(String p) => switch (p) {
  'urgent' => UltronColors.danger,
  'high' => UltronColors.warning,
  'low' => UltronColors.textMuted,
  _ => UltronColors.cloud,
};

class _NotificationsPanel extends ConsumerWidget {
  const _NotificationsPanel();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notes = ref.watch(notificationsProvider);
    return _loading(notes, () {
      final list = notes.value!.take(5).toList();
      if (list.isEmpty) return const _Empty('All quiet.');
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final n in list) NotificationTile(n),
          if (list.any((n) => !n.read))
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                key: const Key('panel-read-all'),
                onPressed: () => ref.read(notificationsProvider.notifier).markAllRead(),
                child: const Text('Mark all read'),
              ),
            ),
        ],
      );
    });
  }
}

/// One notification row (Command Center panel and the bell sheet).
class NotificationTile extends ConsumerWidget {
  const NotificationTile(this.n, {super.key});
  final NotificationItem n;

  @override
  Widget build(BuildContext context, WidgetRef ref) => InkWell(
    key: Key('notification-${n.id}'),
    borderRadius: BorderRadius.circular(8),
    onTap: n.read ? null : () => ref.read(notificationsProvider.notifier).markRead(n.id),
    child: Padding(
      padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 5),
            child: Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: n.read ? Colors.transparent : priorityColor(n.priority),
                border: Border.all(color: priorityColor(n.priority)),
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  n.title,
                  style: TextStyle(
                    fontWeight: n.read ? FontWeight.w400 : FontWeight.w600,
                    color: n.read ? UltronColors.textSecondary : UltronColors.textPrimary,
                  ),
                ),
                if (n.body.isNotEmpty)
                  Text(
                    n.body,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 12, color: UltronColors.textSecondary),
                  ),
                Text(ago(n.createdAt), style: const TextStyle(fontSize: 11, color: UltronColors.textMuted)),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}

class _ActivityPanel extends ConsumerWidget {
  const _ActivityPanel();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final activity = ref.watch(activityProvider);
    return _loading(activity, () {
      final list = activity.value!.take(6).toList();
      if (list.isEmpty) return const _Empty('No activity yet.');
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final a in list)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(_activityIcon(a.kind), size: 15, color: UltronColors.textSecondary),
                  const SizedBox(width: 8),
                  Expanded(child: Text(a.summary, maxLines: 2, overflow: TextOverflow.ellipsis)),
                  const SizedBox(width: 6),
                  Text(ago(a.createdAt), style: const TextStyle(fontSize: 11, color: UltronColors.textMuted)),
                ],
              ),
            ),
        ],
      );
    });
  }

  static IconData _activityIcon(String kind) => switch (kind) {
    _ when kind.startsWith('task.failed') => Icons.error_outline,
    _ when kind.startsWith('task.') => Icons.bolt,
    _ when kind.startsWith('memory.') => Icons.psychology_outlined,
    _ when kind.startsWith('automation.') => Icons.shield_outlined,
    _ when kind.startsWith('mode.') => Icons.tune,
    _ => Icons.circle_outlined,
  };
}

class _AutonomyPanel extends ConsumerWidget {
  const _AutonomyPanel();

  static const areas = [
    ('core', 'ULTRON Core', Icons.hub_outlined),
    ('pc', 'PC', Icons.computer),
    ('phone', 'Phone', Icons.smartphone),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final automation = ref.watch(automationProvider);
    return _loading(automation, () {
      final a = automation.value!;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!a.running)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                a.stopped ? 'Emergency stop is on.' : 'Automation is paused.',
                style: const TextStyle(color: UltronColors.warning),
              ),
            ),
          for (final (area, label, icon) in areas) ...[
            Row(
              children: [
                Icon(icon, size: 16),
                const SizedBox(width: 8),
                Expanded(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis)),
                const SizedBox(width: 8),
                Flexible(
                  child: Text(
                    '${a.levels[area] ?? 3} · ${a.levelNames[a.levels[area] ?? 3] ?? ''}',
                    key: Key('level-label-$area'),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.right,
                    style: const TextStyle(fontSize: 12, color: UltronColors.textSecondary),
                  ),
                ),
              ],
            ),
            Slider(
              key: Key('level-$area'),
              value: (a.levels[area] ?? 3).toDouble(),
              min: 0,
              max: 5,
              divisions: 5,
              label: a.levelNames[a.levels[area] ?? 3],
              onChanged: (v) async {
                try {
                  await ref.read(automationProvider.notifier).setLevel(area, v.round());
                } on ApiException catch (e) {
                  ref.read(noticesProvider.notifier).show(e.message);
                }
              },
            ),
          ],
          const Text(
            'Important or irreversible actions always ask, at every level.',
            style: TextStyle(fontSize: 11.5, color: UltronColors.textMuted),
          ),
        ],
      );
    });
  }
}

/// Opens the notification list (bell in the sidebar and top bar).
Future<void> showNotificationsSheet(BuildContext context) => showModalBottomSheet<void>(
  context: context,
  isScrollControlled: true,
  backgroundColor: UltronColors.backgroundAlt,
  builder: (_) => const _NotificationsSheet(),
);

class _NotificationsSheet extends ConsumerWidget {
  const _NotificationsSheet();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notes = ref.watch(notificationsProvider).value ?? const <NotificationItem>[];
    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.75),
        child: Column(
          key: const Key('notifications-sheet'),
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 12, 4),
              child: Row(
                children: [
                  Text('Notifications', style: Theme.of(context).textTheme.titleLarge),
                  const Spacer(),
                  TextButton(
                    key: const Key('read-all'),
                    onPressed: notes.any((n) => !n.read)
                        ? () => ref.read(notificationsProvider.notifier).markAllRead()
                        : null,
                    child: const Text('Mark all read'),
                  ),
                ],
              ),
            ),
            if (notes.isEmpty)
              const Padding(padding: EdgeInsets.all(20), child: _Empty('No notifications.'))
            else
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                  children: [for (final n in notes) NotificationTile(n)],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// Bell with the number of unread notifications.
class NotificationBell extends ConsumerWidget {
  const NotificationBell({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = ref.watch(unreadCountProvider);
    return IconButton(
      key: const Key('notification-bell'),
      tooltip: unread == 0 ? 'Notifications' : '$unread unread notifications',
      onPressed: () => showNotificationsSheet(context),
      icon: Badge(
        isLabelVisible: unread > 0,
        label: Text('$unread', key: const Key('unread-count')),
        child: Icon(unread > 0 ? Icons.notifications_active_outlined : Icons.notifications_none),
      ),
    );
  }
}
