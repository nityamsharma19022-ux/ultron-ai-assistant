import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/models.dart';
import '../../core/auth/session.dart';
import '../../core/settings/app_settings.dart';
import '../../core/theme/ultron_colors.dart';
import '../../widgets/glass_panel.dart';
import '../../widgets/ultron_logo.dart';
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
          const _AppearanceSection(),
          const SizedBox(height: 16),
          const _VoiceSection(),
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
