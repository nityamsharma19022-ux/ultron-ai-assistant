import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/command_models.dart';
import '../../core/notices.dart';
import '../../core/providers.dart';
import '../../core/api/models.dart';
import '../../core/auth/session.dart';
import '../../core/time_format.dart';
import '../../core/settings/app_settings.dart';
import '../../core/theme/ultron_colors.dart';
import '../../widgets/glass_panel.dart';
import '../../widgets/ultron_logo.dart';
import '../command/command_controller.dart';
import '../voice/voice_controller.dart';
import 'ai_preferences_controller.dart';

const appVersion = '0.3.0';

class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) => Align(
    alignment: Alignment.topCenter,
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 760),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
        children: [
          Text('SETTINGS', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 16),
          const _AiSection(),
          const SizedBox(height: 16),
          const _PersonaSection(),
          const SizedBox(height: 16),
          const _ModesSection(),
          const SizedBox(height: 16),
          const _NotificationSection(),
          const SizedBox(height: 16),
          const _AppearanceSection(),
          const SizedBox(height: 16),
          const _VoiceSection(),
          const SizedBox(height: 16),
          const _DataSection(),
          const SizedBox(height: 16),
          const _AccountSection(),
          const SizedBox(height: 16),
          const _AboutSection(),
        ],
      ),
    ),
  );
}

class _Section extends StatelessWidget {
  const _Section({super.key, required this.title, required this.subtitle, required this.children});
  final String title;
  final String subtitle;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => GlassPanel(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 4),
        Text(subtitle, style: const TextStyle(color: UltronColors.textSecondary, fontSize: 12.5)),
        const SizedBox(height: 16),
        ...children,
      ],
    ),
  );
}

// ------------------------------------------------------------------- AI

class _AiSection extends ConsumerStatefulWidget {
  const _AiSection();

  @override
  ConsumerState<_AiSection> createState() => _AiSectionState();
}

class _AiSectionState extends ConsumerState<_AiSection> {
  bool _saving = false;

  Future<void> _save(AiPreferences p) async {
    setState(() => _saving = true);
    try {
      await ref.read(aiPreferencesProvider.notifier).save(p);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final prefs = ref.watch(aiPreferencesProvider);
    return _Section(
      key: const Key('ai-settings'),
      title: 'AI ROUTING',
      subtitle: 'Stored on ULTRON Core, so every device uses the same choices.',
      children: [
        prefs.when(
          loading: () => const LinearProgressIndicator(minHeight: 2),
          error: (e, _) => Text(
            e is ApiException ? e.message : 'Could not load AI settings',
            style: const TextStyle(color: UltronColors.danger),
          ),
          data: (p) {
            if (p == null) return const SizedBox.shrink();
            final order = _fullOrder(p);
            final wide = MediaQuery.sizeOf(context).width >= 480;
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Where answers come from', style: TextStyle(fontWeight: FontWeight.w600)),
                const SizedBox(height: 8),
                SegmentedButton<String>(
                  key: const Key('ai-mode'),
                  // Icons only where there is room, so labels stay on one line on phones.
                  showSelectedIcon: wide,
                  segments: [
                    ButtonSegment(
                      value: 'auto',
                      label: const Text('Auto'),
                      icon: wide ? const Icon(Icons.auto_mode) : null,
                    ),
                    ButtonSegment(
                      value: 'cloud_only',
                      label: const Text('Cloud only'),
                      icon: wide ? const Icon(Icons.cloud_outlined) : null,
                    ),
                    ButtonSegment(
                      value: 'local_only',
                      label: const Text('Local only'),
                      icon: wide ? const Icon(Icons.memory) : null,
                    ),
                  ],
                  selected: {p.mode},
                  onSelectionChanged: _saving ? null : (v) => _save(p.copyWith(mode: v.first)),
                ),
                const SizedBox(height: 6),
                Text(switch (p.mode) {
                  'cloud_only' => 'Only cloud AI. No local fallback (private chats still use local AI).',
                  'local_only' => 'Only the local model on your PC. Nothing goes to the cloud.',
                  _ => 'Cloud AI first, in the order below; local AI when cloud is unavailable or you are offline.',
                }, style: const TextStyle(fontSize: 12.5, color: UltronColors.textSecondary)),
                const SizedBox(height: 18),
                const Text('Cloud provider order', style: TextStyle(fontWeight: FontWeight.w600)),
                const Text(
                  'Drag to reorder. Providers without an API key are skipped.',
                  style: TextStyle(fontSize: 12.5, color: UltronColors.textSecondary),
                ),
                const SizedBox(height: 8),
                ReorderableListView(
                  key: const Key('cloud-order'),
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  buildDefaultDragHandles: false,
                  onReorderItem: (from, to) {
                    final list = [...order];
                    list.insert(to, list.removeAt(from));
                    _save(p.copyWith(cloudOrder: list));
                  },
                  children: [
                    for (final (i, name) in order.indexed)
                      ListTile(
                        key: ValueKey('provider-$name'),
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        leading: CircleAvatar(
                          radius: 12,
                          backgroundColor: UltronColors.cloud.withValues(alpha: 0.15),
                          child: Text('${i + 1}', style: const TextStyle(fontSize: 11, color: UltronColors.cloud)),
                        ),
                        title: Text(name),
                        trailing: ReorderableDragStartListener(
                          index: i,
                          child: const Icon(Icons.drag_indicator, color: UltronColors.textMuted),
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 10),
                SwitchListTile(
                  key: const Key('private-default'),
                  contentPadding: EdgeInsets.zero,
                  value: p.privateByDefault,
                  onChanged: _saving ? null : (v) => _save(p.copyWith(privateByDefault: v)),
                  title: const Text('New conversations are private'),
                  subtitle: const Text(
                    'Private conversations use local AI only and stay on your machine.',
                    style: TextStyle(fontSize: 12.5),
                  ),
                ),
              ],
            );
          },
        ),
      ],
    );
  }

  /// The user's order followed by any providers they haven't placed yet.
  static List<String> _fullOrder(AiPreferences p) => [
    ...p.cloudOrder.where(p.availableCloudProviders.contains),
    ...p.availableCloudProviders.where((n) => !p.cloudOrder.contains(n)),
  ];
}

// ----------------------------------------------------------- appearance

class _AppearanceSection extends ConsumerWidget {
  const _AppearanceSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(settingsProvider);
    final n = ref.read(settingsProvider.notifier);
    return _Section(
      title: 'APPEARANCE',
      subtitle: 'Saved on this device.',
      children: [
        const Text('Presets', style: TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final p in ThemePreset.values)
              ActionChip(
                key: Key('preset-${p.name}'),
                avatar: CircleAvatar(backgroundColor: p.accent.color, radius: 7),
                label: Text(p.label),
                onPressed: () => n.applyPreset(p),
              ),
          ],
        ),
        const SizedBox(height: 20),
        const Text('Background', style: TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        SegmentedButton<BackgroundStyle>(
          key: const Key('background-style'),
          segments: [for (final b in BackgroundStyle.values) ButtonSegment(value: b, label: Text(b.label))],
          selected: {s.background},
          onSelectionChanged: (v) => n.setBackground(v.first),
        ),
        const SizedBox(height: 20),
        const Text('Accent colour', style: TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 10),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            for (final a in UltronAccent.values)
              Semantics(
                label: '${a.label} accent${a == s.accent ? ', selected' : ''}',
                button: true,
                child: InkWell(
                  key: Key('accent-${a.name}'),
                  customBorder: const CircleBorder(),
                  onTap: () => n.setAccent(a),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    width: 40,
                    height: 40,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: a.color,
                      border: Border.all(color: a == s.accent ? Colors.white : Colors.transparent, width: 3),
                      boxShadow: [if (a == s.accent) BoxShadow(color: a.color.withValues(alpha: 0.7), blurRadius: 14)],
                    ),
                  ),
                ),
              ),
          ],
        ),
        const SizedBox(height: 20),
        const Text('Animations', style: TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        SegmentedButton<MotionLevel>(
          key: const Key('motion-level'),
          segments: [for (final m in MotionLevel.values) ButtonSegment(value: m, label: Text(m.label))],
          selected: {s.motion},
          onSelectionChanged: (v) => n.setMotion(v.first),
        ),
        const SizedBox(height: 6),
        const Text(
          'Reduced slows the visualizer and drops particles; Off shows a still image.',
          style: TextStyle(fontSize: 12.5, color: UltronColors.textSecondary),
        ),
      ],
    );
  }
}

// ------------------------------------------------- personality and speed

class _PersonaSection extends ConsumerStatefulWidget {
  const _PersonaSection();

  @override
  ConsumerState<_PersonaSection> createState() => _PersonaSectionState();
}

class _PersonaSectionState extends ConsumerState<_PersonaSection> {
  final _address = TextEditingController();
  bool _loaded = false;

  @override
  void dispose() {
    _address.dispose();
    super.dispose();
  }

  Future<void> _save(AiPreferences updated) async {
    try {
      await ref.read(aiPreferencesProvider.notifier).save(updated);
    } on ApiException catch (e) {
      ref.read(noticesProvider.notifier).show(e.message);
    }
  }

  static const speeds = {
    'instant': ('Instant', 'Fast model, short answers'),
    'balanced': ('Balanced', 'Good answers at good speed'),
    'deep': ('Deep reasoning', 'Strongest model, careful answers (slower)'),
  };

  @override
  Widget build(BuildContext context) {
    final prefs = ref.watch(aiPreferencesProvider).value;
    if (prefs == null) return const SizedBox();
    if (!_loaded) {
      _address.text = prefs.addressAs;
      _loaded = true;
    }
    return _Section(
      key: const Key('persona-settings'),
      title: 'PERSONALITY & SPEED',
      subtitle: 'Synced to all your devices.',
      children: [
        const Text('Response speed', style: TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        SegmentedButton<String>(
          key: const Key('response-mode'),
          segments: [for (final e in speeds.entries) ButtonSegment(value: e.key, label: Text(e.value.$1))],
          selected: {prefs.responseMode},
          onSelectionChanged: (v) => _save(prefs.copyWith(responseMode: v.first)),
        ),
        const SizedBox(height: 6),
        Text(
          speeds[prefs.responseMode]?.$2 ?? '',
          style: const TextStyle(fontSize: 12.5, color: UltronColors.textSecondary),
        ),
        const SizedBox(height: 20),
        const Text('Clock', style: TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        SegmentedButton<String>(
          key: const Key('time-format'),
          segments: [
            ButtonSegment(value: '12h', label: Text('12-hour (${clockText(21, 30)})')),
            ButtonSegment(value: '24h', label: Text('24-hour (${clockText(21, 30, h24: true)})')),
          ],
          selected: {prefs.timeFormat},
          onSelectionChanged: (v) => _save(prefs.copyWith(timeFormat: v.first)),
        ),
        const SizedBox(height: 20),
        TextField(
          key: const Key('address-as'),
          controller: _address,
          maxLength: 40,
          decoration: const InputDecoration(
            labelText: 'ULTRON addresses you as',
            hintText: 'Sir',
            helperText: 'Leave empty for no title',
          ),
          onSubmitted: (v) => _save(prefs.copyWith(addressAs: v.trim())),
        ),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton(
            key: const Key('save-address'),
            onPressed: () => _save(prefs.copyWith(addressAs: _address.text.trim())),
            child: const Text('Save'),
          ),
        ),
        const Text(
          'ULTRON is polite, warm and patient, admits when it is unsure, and never pretends to have feelings.',
          style: TextStyle(fontSize: 12, color: UltronColors.textMuted),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------- modes

class _ModesSection extends ConsumerWidget {
  const _ModesSection();

  Future<void> _guard(WidgetRef ref, Future<void> Function() action) async {
    try {
      await action();
    } on ApiException catch (e) {
      ref.read(noticesProvider.notifier).show(e.message);
    }
  }

  Future<void> _create(BuildContext context, WidgetRef ref) async {
    final draft = await showDialog<(String, String, bool)>(context: context, builder: (_) => const _ModeDialog());
    if (draft == null || draft.$1.trim().isEmpty) return;
    await _guard(
      ref,
      () =>
          ref.read(modesProvider.notifier).create(name: draft.$1.trim(), personality: draft.$2.trim(), quiet: draft.$3),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final modes = ref.watch(modesProvider);
    return _Section(
      key: const Key('modes-settings'),
      title: 'OPERATING MODE',
      subtitle:
          'Changes how ULTRON talks, which AI it prefers, whether it uses memories, what it may act on '
          'and whether it stays quiet. Synced to all your devices.',
      children: [
        modes.when(
          loading: () => const LinearProgressIndicator(minHeight: 2),
          error: (e, _) => Text(e is ApiException ? e.message : 'Could not load modes'),
          data: (list) => Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final m in list)
                InputChip(
                  key: Key('mode-option-${m.key}'),
                  selected: m.active,
                  showCheckmark: false,
                  avatar: m.quiet ? const Icon(Icons.notifications_paused_outlined, size: 16) : null,
                  label: Text(m.name),
                  tooltip: _describe(m),
                  // Enabled even when active, so it shows as selected rather than greyed out.
                  onPressed: () {
                    if (!m.active) _guard(ref, () => ref.read(modesProvider.notifier).activate(m.key));
                  },
                  onDeleted: m.builtin ? null : () => _guard(ref, () => ref.read(modesProvider.notifier).remove(m.key)),
                ),
              ActionChip(
                key: const Key('add-mode'),
                avatar: const Icon(Icons.add, size: 16),
                label: const Text('Custom mode'),
                onPressed: () => _create(context, ref),
              ),
            ],
          ),
        ),
      ],
    );
  }

  static String _describe(AssistantModeInfo m) => [
    if (m.personality.isNotEmpty) m.personality,
    if (m.aiMode != null) 'AI: ${m.aiMode}',
    if (!m.memory) 'no memories',
    if (m.toolAreas.length < 3) 'acts on: ${m.toolAreas.isEmpty ? 'nothing' : m.toolAreas.join(', ')}',
    if (m.quiet) 'quiet',
  ].join(' · ');
}

class _ModeDialog extends StatefulWidget {
  const _ModeDialog();

  @override
  State<_ModeDialog> createState() => _ModeDialogState();
}

class _ModeDialogState extends State<_ModeDialog> {
  final _name = TextEditingController();
  final _personality = TextEditingController();
  bool _quiet = false;

  @override
  void dispose() {
    _name.dispose();
    _personality.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    backgroundColor: UltronColors.surface,
    title: const Text('New mode'),
    content: SizedBox(
      width: 440,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            key: const Key('mode-name'),
            controller: _name,
            autofocus: true,
            maxLength: 60,
            decoration: const InputDecoration(labelText: 'Name', hintText: 'e.g. Exam week'),
          ),
          TextField(
            key: const Key('mode-personality'),
            controller: _personality,
            maxLines: 3,
            maxLength: 2000,
            decoration: const InputDecoration(
              labelText: 'How ULTRON should behave',
              hintText: 'e.g. Short answers, quiz me, no small talk.',
            ),
          ),
          SwitchListTile(
            key: const Key('mode-quiet'),
            contentPadding: EdgeInsets.zero,
            value: _quiet,
            onChanged: (v) => setState(() => _quiet = v),
            title: const Text('Quiet (only important notifications)'),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
      FilledButton(
        key: const Key('mode-save'),
        onPressed: () => Navigator.pop(context, (_name.text, _personality.text, _quiet)),
        child: const Text('Create'),
      ),
    ],
  );
}

// -------------------------------------------------------- notifications

final notificationSettingsProvider = FutureProvider<NotificationSettingsInfo>(
  (ref) => ref.watch(apiProvider).notificationSettings(),
);

class _NotificationSection extends ConsumerWidget {
  const _NotificationSection();

  static const priorities = {'low': 'Everything', 'normal': 'Normal and up', 'high': 'Important only'};

  Future<void> _save(WidgetRef ref, NotificationSettingsInfo s) async {
    try {
      await ref.read(apiProvider).saveNotificationSettings(s);
      ref.invalidate(notificationSettingsProvider);
    } on ApiException catch (e) {
      ref.read(noticesProvider.notifier).show(e.message);
    }
  }

  static NotificationSettingsInfo _with(
    NotificationSettingsInfo s, {
    String? Function()? quietStart,
    String? Function()? quietEnd,
    String? minPriority,
    String? Function()? briefing,
  }) => NotificationSettingsInfo(
    quietStart: quietStart != null ? quietStart() : s.quietStart,
    quietEnd: quietEnd != null ? quietEnd() : s.quietEnd,
    // The phone/PC clock decides "local" time for quiet hours.
    utcOffsetMinutes: DateTime.now().timeZoneOffset.inMinutes,
    minPriority: minPriority ?? s.minPriority,
    dailyBriefing: briefing != null ? briefing() : s.dailyBriefing,
  );

  Future<String?> _pickTime(BuildContext context, String? current, bool h24) async {
    final parts = (current ?? '22:00').split(':');
    final t = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: int.parse(parts[0]), minute: int.parse(parts[1])),
      // The picker follows ULTRON's clock setting (12-hour unless changed).
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(alwaysUse24HourFormat: h24),
        child: child!,
      ),
    );
    if (t == null) return null;
    return '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(notificationSettingsProvider);
    final h24 = ref.watch(use24HourProvider);
    String t(String? v) => hhmmText(v, h24: h24);
    return _Section(
      key: const Key('notification-settings'),
      title: 'NOTIFICATIONS',
      subtitle: 'Urgent alerts always come through. Everything stays in the bell list.',
      children: [
        settings.when(
          loading: () => const LinearProgressIndicator(minHeight: 2),
          error: (e, _) => Text(e is ApiException ? e.message : 'Could not load notification settings'),
          data: (s) => Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              DropdownButtonFormField<String>(
                key: const Key('min-priority'),
                initialValue: s.minPriority == 'urgent' ? 'high' : s.minPriority,
                decoration: const InputDecoration(labelText: 'Pop up'),
                items: [for (final e in priorities.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
                onChanged: (v) => _save(ref, _with(s, minPriority: v)),
              ),
              SwitchListTile(
                key: const Key('quiet-hours'),
                contentPadding: EdgeInsets.zero,
                value: s.quietStart != null,
                title: const Text('Quiet hours'),
                subtitle: Text(s.quietStart == null ? 'Not set' : '${t(s.quietStart)} – ${t(s.quietEnd)}'),
                onChanged: (on) =>
                    _save(ref, _with(s, quietStart: () => on ? '22:00' : null, quietEnd: () => on ? '07:00' : null)),
              ),
              if (s.quietStart != null)
                Wrap(
                  spacing: 8,
                  children: [
                    OutlinedButton(
                      key: const Key('quiet-start'),
                      onPressed: () async {
                        final t = await _pickTime(context, s.quietStart, h24);
                        if (t != null) await _save(ref, _with(s, quietStart: () => t));
                      },
                      child: Text('From ${t(s.quietStart)}'),
                    ),
                    OutlinedButton(
                      key: const Key('quiet-end'),
                      onPressed: () async {
                        final t = await _pickTime(context, s.quietEnd, h24);
                        if (t != null) await _save(ref, _with(s, quietEnd: () => t));
                      },
                      child: Text('Until ${t(s.quietEnd)}'),
                    ),
                  ],
                ),
              SwitchListTile(
                key: const Key('daily-briefing'),
                contentPadding: EdgeInsets.zero,
                value: s.dailyBriefing != null,
                title: const Text('Daily briefing'),
                subtitle: Text(
                  s.dailyBriefing == null
                      ? 'Not scheduled'
                      : 'At ${t(s.dailyBriefing)}: your reminders, tasks and devices for the day',
                ),
                onChanged: (on) => _save(ref, _with(s, briefing: () => on ? '08:00' : null)),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// ----------------------------------------------------------------- data

class _DataSection extends ConsumerStatefulWidget {
  const _DataSection();

  @override
  ConsumerState<_DataSection> createState() => _DataSectionState();
}

class _DataSectionState extends ConsumerState<_DataSection> {
  bool _busy = false;

  Future<void> _export() async {
    setState(() => _busy = true);
    try {
      final data = await ref.read(apiProvider).exportAllData();
      await Clipboard.setData(ClipboardData(text: const JsonEncoder.withIndent('  ').convert(data)));
      final convs = (data['conversations'] as List?)?.length ?? 0;
      final mems = (data['memories'] as List?)?.length ?? 0;
      ref
          .read(noticesProvider.notifier)
          .show('Copied your data ($convs conversations, $mems memories) to the clipboard as JSON.');
    } on ApiException catch (e) {
      ref.read(noticesProvider.notifier).show(e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => _Section(
    key: const Key('data-settings'),
    title: 'YOUR DATA',
    subtitle:
        'Export conversations, memories, tasks, reminders, modes and settings as JSON (never passwords '
        'or sign-in tokens). Full database backups: see the setup guide.',
    children: [
      OutlinedButton.icon(
        key: const Key('export-all'),
        onPressed: _busy ? null : _export,
        icon: _busy
            ? const SizedBox.square(dimension: 16, child: CircularProgressIndicator(strokeWidth: 2))
            : const Icon(Icons.download_outlined),
        label: const Text('Export all data'),
      ),
    ],
  );
}

// ---------------------------------------------------------------- voice

class _VoiceSection extends ConsumerWidget {
  const _VoiceSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(settingsProvider);
    final n = ref.read(settingsProvider.notifier);
    final speaking = ref.watch(voiceProvider.select((v) => v.speaking));
    final onDevice = ref.watch(speechInputProvider).recognisesOnDevice;
    const note = TextStyle(fontSize: 12.5, color: UltronColors.textSecondary);
    return _Section(
      key: const Key('voice-settings'),
      title: 'VOICE',
      subtitle: 'Tap the mic in the chat box to talk; tap it again to send.',
      children: [
        SwitchListTile(
          key: const Key('speak-replies'),
          contentPadding: EdgeInsets.zero,
          value: s.speakReplies,
          onChanged: n.setSpeakReplies,
          title: const Text('Read replies aloud'),
        ),
        const SizedBox(height: 6),
        Text('Speaking speed: ${(s.speechRate * 2).toStringAsFixed(1)}×'),
        Slider(
          key: const Key('speech-rate'),
          value: s.speechRate,
          min: 0.25,
          max: 0.9,
          divisions: 13,
          onChanged: n.setSpeechRate,
        ),
        OutlinedButton.icon(
          key: const Key('test-voice'),
          onPressed: speaking
              ? ref.read(voiceProvider.notifier).stopSpeaking
              : () => ref
                    .read(voiceProvider.notifier)
                    .speak('ULTRON voice check. This is how replies will sound.', private: true),
          icon: Icon(speaking ? Icons.stop : Icons.volume_up_outlined),
          label: Text(speaking ? 'Stop' : 'Test voice'),
        ),
        const SizedBox(height: 14),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.shield_outlined, size: 18, color: UltronColors.local),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                onDevice
                    ? 'Speech recognition runs on this device (Windows Speech), so voice input also works in '
                          'private conversations. Private replies are read with voices installed on this PC.'
                    : "This device's speech recognition may use an online service (on Android usually "
                          "Google's), so voice input is off in private conversations. Private replies are read "
                          'aloud only with an offline voice.',
                key: const Key('voice-privacy-note'),
                style: note,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

// -------------------------------------------------------------- account

class _AccountSection extends ConsumerWidget {
  const _AccountSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    final backend = ref.watch(settingsProvider.select((s) => s.backendUrl));
    final me = session is SignedIn ? session.me : null;
    return _Section(
      title: 'ACCOUNT',
      subtitle: 'Signed in to your ULTRON Core.',
      children: [
        if (me != null) ...[
          _Info('Signed in as', me.user.email),
          _Info('This device', '${me.device.name} (${me.device.platform})'),
        ],
        _Info('ULTRON Core', backend),
        const SizedBox(height: 14),
        OutlinedButton.icon(
          key: const Key('sign-out'),
          onPressed: () => ref.read(sessionProvider.notifier).signOut(),
          icon: const Icon(Icons.logout),
          label: const Text('Sign out of this device'),
        ),
        const SizedBox(height: 6),
        const Text(
          'To use a different server address, sign out and enter it on the sign-in screen.',
          style: TextStyle(fontSize: 12.5, color: UltronColors.textSecondary),
        ),
      ],
    );
  }
}

class _Info extends StatelessWidget {
  const _Info(this.label, this.value);
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Row(
      children: [
        SizedBox(
          width: 120,
          child: Text(label, style: const TextStyle(color: UltronColors.textSecondary)),
        ),
        Expanded(child: SelectableText(value)),
      ],
    ),
  );
}

// ---------------------------------------------------------------- about

class _AboutSection extends StatelessWidget {
  const _AboutSection();

  @override
  Widget build(BuildContext context) => _Section(
    title: 'ABOUT',
    subtitle: 'ULTRON personal AI assistant',
    children: [
      const _Info('Version', appVersion),
      const SizedBox(height: 10),
      OutlinedButton.icon(
        onPressed: () => showLicensePage(
          context: context,
          applicationName: 'ULTRON',
          applicationVersion: appVersion,
          applicationIcon: const Padding(padding: EdgeInsets.all(12), child: UltronLogo(size: 18, showWordmark: false)),
        ),
        icon: const Icon(Icons.description_outlined),
        label: const Text('Open-source licences'),
      ),
    ],
  );
}
