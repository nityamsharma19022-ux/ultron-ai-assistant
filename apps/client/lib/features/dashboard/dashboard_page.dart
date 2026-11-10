import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/command_models.dart';
import '../../core/api/models.dart';
import '../../core/api/task_models.dart';
import '../../core/platform/native.dart';
import '../../core/providers.dart';
import '../../core/auth/session.dart';
import '../../core/status/system_status.dart';
import '../../core/theme/ultron_colors.dart';
import '../../core/time_format.dart';
import '../../widgets/connection_indicator.dart';
import '../../widgets/glass_panel.dart';
import '../agent/phone_agent.dart';
import '../assistant/assistant_screen.dart';
import '../visualizer/chat_visualizer.dart';
import '../../core/settings/app_settings.dart';
import 'dashboard_controller.dart';

/// System status: ULTRON Core, AI providers, local model, devices.
class DashboardPage extends ConsumerWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(systemStatusProvider);
    return LayoutBuilder(
      builder: (context, c) {
        final columns = c.maxWidth >= 1100 ? 2 : 1;
        final cards = <Widget>[
          _CoreCard(status: status),
          _LocalModelCard(status: status),
          _ProvidersCard(status: status),
          const _DevicesCard(),
          const _AgentsCard(),
          const _AssistantCard(),
          const _UsageCard(),
        ];
        return RefreshIndicator(
          onRefresh: () async {
            await ref.read(systemStatusProvider.notifier).refresh();
            ref.invalidate(devicesProvider);
            ref.invalidate(agentsProvider);
          },
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
            children: [
              _Header(status: status),
              const SizedBox(height: 16),
              if (columns == 1)
                for (final card in cards) Padding(padding: const EdgeInsets.only(bottom: 16), child: card)
              else
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Column(
                        children: [
                          cards[0],
                          const SizedBox(height: 16),
                          cards[1],
                          const SizedBox(height: 16),
                          cards[5],
                          const SizedBox(height: 16),
                          cards[6],
                        ],
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        children: [
                          cards[2],
                          const SizedBox(height: 16),
                          cards[4],
                          const SizedBox(height: 16),
                          cards[3],
                        ],
                      ),
                    ),
                  ],
                ),
            ],
          ),
        );
      },
    );
  }
}

class _Header extends ConsumerWidget {
  const _Header({required this.status});
  final SystemStatus status;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final checked = status.checkedAt;
    return Row(
      children: [
        const ChatVisualizer(size: 56),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('SYSTEM STATUS', style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 4),
              Text(
                checked == null
                    ? 'Checking…'
                    : 'Last checked ${_time(checked, h24: ref.watch(use24HourProvider))} · refreshes every 20 s',
                style: Theme.of(context).textTheme.labelSmall,
              ),
            ],
          ),
        ),
        IconButton(
          key: const Key('refresh-status'),
          tooltip: 'Refresh now',
          icon: const Icon(Icons.refresh),
          onPressed: () {
            ref.read(systemStatusProvider.notifier).refresh();
            ref.invalidate(devicesProvider);
          },
        ),
      ],
    );
  }
}

/// "9:24:05 PM" (seconds help show the status is live).
String _time(DateTime t, {bool h24 = false}) {
  final base = clockText(t.hour, t.minute, h24: h24);
  final sec = t.second.toString().padLeft(2, '0');
  return h24 ? '$base:$sec' : base.replaceFirst(' ', ':$sec ');
}

/// Card with a titled header.
class _Card extends StatelessWidget {
  const _Card({super.key, required this.title, required this.icon, required this.child, this.trailing});
  final String title;
  final IconData icon;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => GlassPanel(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 18, color: Theme.of(context).colorScheme.primary),
            const SizedBox(width: 10),
            Expanded(child: Text(title, style: Theme.of(context).textTheme.titleLarge)),
            ?trailing,
          ],
        ),
        const SizedBox(height: 14),
        child,
      ],
    ),
  );
}

class _Row extends StatelessWidget {
  const _Row(this.label, this.value, {this.color, this.detail});
  final String label;
  final String value;
  final Color? color;
  final String? detail;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 5),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 130,
          child: Text(label, style: const TextStyle(color: UltronColors.textSecondary, fontSize: 13)),
        ),
        if (color != null) ...[
          Padding(
            padding: const EdgeInsets.only(top: 5),
            child: StatusDot(color: color!, size: 7),
          ),
          const SizedBox(width: 8),
        ],
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(value, style: const TextStyle(fontSize: 13.5)),
              if (detail != null) Text(detail!, style: const TextStyle(fontSize: 12, color: UltronColors.textMuted)),
            ],
          ),
        ),
      ],
    ),
  );
}

Color _checkColor(String s) => switch (s) {
  'ok' || 'ready' => UltronColors.success,
  'not_configured' || 'unknown' => UltronColors.textMuted,
  'unavailable' => UltronColors.warning,
  _ when s.startsWith('cooldown') => UltronColors.warning,
  _ => UltronColors.danger,
};

class _CoreCard extends StatelessWidget {
  const _CoreCard({required this.status});
  final SystemStatus status;

  @override
  Widget build(BuildContext context) {
    final live = status.live;
    final ready = status.ready;
    final (linkText, linkColor) = switch (status.link) {
      BackendLink.checking => ('Checking…', UltronColors.textSecondary),
      BackendLink.online => ('Online', UltronColors.success),
      BackendLink.degraded => ('Degraded', UltronColors.warning),
      BackendLink.offline => ('Offline', UltronColors.danger),
    };
    return _Card(
      key: const Key('core-card'),
      title: 'ULTRON CORE',
      icon: Icons.hub_outlined,
      child: Column(
        children: [
          _Row('Connection', linkText, color: linkColor, detail: status.error),
          if (live != null) ...[_Row('Node', live.nodeId, detail: '${live.deployment} backend · v${live.version}')],
          if (ready != null) ...[
            _Row(
              'Database',
              ready.checkStatus('database'),
              color: _checkColor(ready.checkStatus('database')),
              detail: '${ready.dbMode} database',
            ),
            _Row('Redis', ready.checkStatus('redis'), color: _checkColor(ready.checkStatus('redis'))),
          ],
        ],
      ),
    );
  }
}

/// Results of "Test" per provider, kept while the app runs.
final providerTestsProvider = NotifierProvider<ProviderTests, Map<String, AsyncValue<ProviderTestResult>>>(
  ProviderTests.new,
);

class ProviderTests extends Notifier<Map<String, AsyncValue<ProviderTestResult>>> {
  @override
  Map<String, AsyncValue<ProviderTestResult>> build() => const {};

  Future<void> run(String provider) async {
    state = {...state, provider: const AsyncLoading()};
    try {
      final r = await ref.read(apiProvider).testProvider(provider);
      state = {...state, provider: AsyncData(r)};
    } on ApiException catch (e, st) {
      state = {...state, provider: AsyncError(e, st)};
    }
  }
}

class _ProvidersCard extends ConsumerWidget {
  const _ProvidersCard({required this.status});
  final SystemStatus status;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ai = status.ai;
    final tests = ref.watch(providerTestsProvider);
    return _Card(
      key: const Key('providers-card'),
      title: 'AI SOURCES',
      icon: Icons.auto_awesome_outlined,
      trailing: ai == null ? null : Text('mode: ${ai.mode}', style: Theme.of(context).textTheme.labelSmall),
      child: ai == null
          ? const Text('Not available', style: TextStyle(color: UltronColors.textMuted))
          : Column(
              children: [
                _Row(
                  'Cloud AI',
                  ai.cloudAvailable ? 'Available' : 'Unavailable',
                  color: ai.cloudAvailable ? UltronColors.cloud : UltronColors.textMuted,
                ),
                _Row(
                  'Local AI',
                  ai.localAiAvailable ? 'Available' : 'Unavailable',
                  color: ai.localAiAvailable ? UltronColors.local : UltronColors.textMuted,
                ),
                _Row(
                  'Private chats',
                  ai.privateConversationsSupported ? 'Supported' : 'Not available now',
                  color: ai.privateConversationsSupported ? UltronColors.local : UltronColors.textMuted,
                ),
                const Divider(height: 24),
                for (final p in ai.providers) ...[
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: _Row(
                          providerDisplayName(p.name),
                          _providerLabel(p),
                          color: _checkColor(p.status),
                          detail: [p.kind, ?p.model, ?p.reason].join(' · '),
                        ),
                      ),
                      if (p.configured)
                        TextButton(
                          key: Key('test-${p.name}'),
                          onPressed: tests[p.name] is AsyncLoading
                              ? null
                              : () => ref.read(providerTestsProvider.notifier).run(p.name),
                          child: tests[p.name] is AsyncLoading
                              ? const SizedBox.square(dimension: 14, child: CircularProgressIndicator(strokeWidth: 2))
                              : const Text('Test'),
                        ),
                    ],
                  ),
                  if (tests[p.name] case final t? when t is! AsyncLoading)
                    Padding(
                      padding: const EdgeInsets.only(left: 130, bottom: 6),
                      child: Text(
                        key: Key('test-result-${p.name}'),
                        switch (t) {
                          AsyncData(:final value) when value.ok =>
                            '✓ Answered "${value.reply}" in ${value.seconds}s via ${value.model ?? p.name}',
                          AsyncData(:final value) => '✗ ${value.error ?? 'No answer'}',
                          AsyncError(:final error) => '✗ ${error is ApiException ? error.message : error}',
                          _ => '',
                        },
                        style: TextStyle(
                          fontSize: 12,
                          color: t is AsyncData<ProviderTestResult> && t.value.ok
                              ? UltronColors.success
                              : UltronColors.danger,
                        ),
                      ),
                    ),
                ],
              ],
            ),
    );
  }

  static String _providerLabel(ProviderStatus p) => switch (p.status) {
    'ready' => 'Ready',
    'not_configured' => 'Not set up',
    'unavailable' => 'Unavailable',
    final s when s.startsWith('cooldown_') =>
      'Paused (${s.substring(9).replaceAll('_', ' ')}${p.cooldownRemainingSeconds == null ? '' : ', ${p.cooldownRemainingSeconds}s'})',
    final s => s,
  };
}

class _LocalModelCard extends ConsumerWidget {
  const _LocalModelCard({required this.status});
  final SystemStatus status;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final local = status.localProvider;
    final warm = ref.watch(warmupProvider);
    final installed = local?.available ?? false;
    final loaded = local?.modelLoaded;
    return _Card(
      key: const Key('local-model-card'),
      title: 'LOCAL MODEL',
      icon: Icons.memory,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (local == null)
            const _Row(
              'Status',
              'Not set up',
              color: UltronColors.textMuted,
              detail: 'Install Ollama and set ULTRON_OLLAMA_MODEL on the PC.',
            )
          else ...[
            _Row('Model', local.model ?? '—'),
            _Row(
              'Installed',
              installed ? 'Yes' : 'No',
              color: installed ? UltronColors.success : UltronColors.warning,
              detail: local.reason,
            ),
            _Row('In memory', switch (loaded) {
              true => 'Loaded (fast replies)',
              false => 'Not loaded (first reply will be slower)',
              null => 'Unknown',
            }, color: loaded == true ? UltronColors.success : UltronColors.textMuted),
            if (local.processor case final p?)
              _Row(
                'Runs on',
                switch (p) {
                  'gpu' => 'Graphics card (GPU)',
                  'partial' => 'Partly GPU, partly CPU',
                  _ => 'Processor (CPU), slower',
                },
                color: p == 'gpu' ? UltronColors.success : UltronColors.warning,
                detail: p == 'gpu' ? null : 'See docs/PERFORMANCE_REPORT.md for how to use the GPU.',
              ),
          ],
          const SizedBox(height: 12),
          Wrap(
            spacing: 12,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              FilledButton.icon(
                key: const Key('warmup-button'),
                onPressed: (local == null || !installed || warm is WarmupRunning)
                    ? null
                    : () async {
                        await ref.read(warmupProvider.notifier).run();
                        await ref.read(systemStatusProvider.notifier).refresh();
                      },
                icon: warm is WarmupRunning
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.bolt),
                label: Text(warm is WarmupRunning ? 'LOADING…' : 'WARM UP'),
              ),
              switch (warm) {
                WarmupDone(:final result) => Text(
                  result.alreadyLoaded ? 'Already loaded' : 'Loaded in ${result.seconds.toStringAsFixed(1)} s',
                  key: const Key('warmup-result'),
                  style: const TextStyle(color: UltronColors.success, fontSize: 13),
                ),
                WarmupFailed(:final message) => Text(
                  message,
                  key: const Key('warmup-result'),
                  style: const TextStyle(color: UltronColors.danger, fontSize: 13),
                ),
                _ => const SizedBox.shrink(),
              },
            ],
          ),
        ],
      ),
    );
  }
}

class _DevicesCard extends ConsumerWidget {
  const _DevicesCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final devices = ref.watch(devicesProvider);
    final session = ref.watch(sessionProvider);
    final currentId = session is SignedIn ? session.me.device.id : null;
    return _Card(
      key: const Key('devices-card'),
      title: 'DEVICES',
      icon: Icons.devices_outlined,
      trailing: TextButton.icon(
        key: const Key('pair-device'),
        onPressed: () => showDialog<void>(context: context, builder: (_) => const PairingDialog()),
        icon: const Icon(Icons.add_link, size: 18),
        label: const Text('Pair a device'),
      ),
      child: devices.when(
        loading: () => const Padding(padding: EdgeInsets.all(8), child: LinearProgressIndicator(minHeight: 2)),
        error: (e, _) => Text(e is ApiException ? e.message : 'Could not load devices'),
        data: (list) => Column(
          children: [
            for (final d in list.where((d) => !d.isRevoked))
              ListTile(
                key: Key('device-${d.id}'),
                contentPadding: EdgeInsets.zero,
                dense: true,
                leading: Icon(switch (d.platform) {
                  'android' => Icons.phone_android,
                  'windows' => Icons.desktop_windows_outlined,
                  _ => Icons.devices_other,
                }, color: UltronColors.textSecondary),
                title: Text(d.id == currentId ? '${d.name} (this device)' : d.name),
                subtitle: Text(
                  d.lastSeenAt == null
                      ? d.platform
                      : '${d.platform} · last active ${_date(d.lastSeenAt!, ref.watch(use24HourProvider))}',
                  style: const TextStyle(fontSize: 11.5, color: UltronColors.textMuted),
                ),
                trailing: d.id == currentId
                    ? null
                    : TextButton(
                        key: Key('revoke-${d.id}'),
                        onPressed: () => _confirmRevoke(context, ref, d),
                        child: const Text('Sign out'),
                      ),
              ),
          ],
        ),
      ),
    );
  }

  static String _date(DateTime t, bool h24) => dayTimeText(t, h24: h24);

  Future<void> _confirmRevoke(BuildContext context, WidgetRef ref, DeviceInfo d) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: UltronColors.surface,
        title: const Text('Sign out this device?'),
        content: Text('"${d.name}" will need to sign in again.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(
            key: const Key('confirm-revoke'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Sign out'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(devicesProvider.notifier).revoke(d.id);
    } on ApiException catch (e) {
      if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }
}

/// Devices running ULTRON agents (the Windows agent, the phone app).
final agentsProvider = FutureProvider<List<AgentStatus>>((ref) => ref.watch(apiProvider).agents());

class _AgentsCard extends ConsumerWidget {
  const _AgentsCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final agents = ref.watch(agentsProvider);
    return _Card(
      key: const Key('agents-card'),
      title: 'AGENTS',
      icon: Icons.smart_toy_outlined,
      child: agents.when(
        loading: () => const LinearProgressIndicator(minHeight: 2),
        error: (e, _) => Text(e is ApiException ? e.message : 'Could not load agents'),
        data: (list) => list.isEmpty
            ? const Text(
                'No agents yet. Install the ULTRON Windows agent on your PC (apps/agent) so ULTRON '
                'can act there; the phone app acts as the phone agent while it is open.',
                style: TextStyle(color: UltronColors.textSecondary, fontSize: 13),
              )
            : Column(
                children: [
                  for (final a in list)
                    _Row(
                      a.deviceName,
                      a.online ? 'Online' : 'Offline',
                      color: a.online ? UltronColors.success : UltronColors.textMuted,
                      detail: [
                        a.target == 'windows' ? 'PC agent' : 'Phone',
                        '${a.tools.length} actions',
                        if ((a.capabilities['apps'] ?? const []).isNotEmpty && a.target == 'windows')
                          'apps: ${a.capabilities['apps']!.join(', ')}',
                        if ((a.capabilities['workflows'] ?? const []).isNotEmpty)
                          'workflows: ${a.capabilities['workflows']!.join(', ')}',
                      ].join(' · '),
                    ),
                ],
              ),
      ),
    );
  }
}

final defaultAssistantProvider = FutureProvider<bool?>(
  (ref) => ref.watch(assistantPlatformProvider).isDefaultAssistant(),
);

class _AssistantCard extends ConsumerWidget {
  const _AssistantCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final platform = ref.watch(assistantPlatformProvider);
    final isDefault = ref.watch(defaultAssistantProvider).value;
    final phoneAgent = ref.watch(phoneAgentProvider);
    return _Card(
      key: const Key('assistant-card'),
      title: 'ASSISTANT',
      icon: Icons.graphic_eq,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (platform.supported) ...[
            _Row(
              'Phone assistant',
              isDefault == true ? 'ULTRON is your digital assistant' : 'Not your digital assistant yet',
              color: isDefault == true ? UltronColors.success : UltronColors.warning,
              detail: isDefault == true
                  ? 'Long-press the home button, swipe from a corner or use the power button '
                        '(depending on your phone) to talk to ULTRON.'
                  : 'Choose ULTRON in Settings → Apps → Default apps → Digital assistant app.',
            ),
            _Row(
              'Phone actions',
              phoneAgent.active ? 'Ready while ULTRON is open' : 'Off',
              color: phoneAgent.active ? UltronColors.success : UltronColors.textMuted,
              detail: phoneAgent.error ?? phoneAgent.lastStep,
            ),
          ] else
            const _Row(
              'Phone assistant',
              'Set up on your Android phone',
              color: UltronColors.textMuted,
              detail: 'On this device, use the Assistant button or the Tasks command bar.',
            ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              FilledButton.icon(
                key: const Key('try-assistant'),
                onPressed: () => AssistantScreen.open(context),
                icon: const Icon(Icons.mic),
                label: const Text('Talk to ULTRON'),
              ),
              if (platform.supported)
                OutlinedButton(
                  key: const Key('choose-assistant'),
                  onPressed: () async {
                    await platform.openAssistantSettings();
                    ref.invalidate(defaultAssistantProvider);
                  },
                  child: const Text('Choose default assistant'),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Shows a one-time code for signing in a new device (phone or PC agent).
class PairingDialog extends ConsumerStatefulWidget {
  const PairingDialog({super.key});

  @override
  ConsumerState<PairingDialog> createState() => _PairingDialogState();
}

class _PairingDialogState extends ConsumerState<PairingDialog> {
  late final Future<PairingCode> _code = ref.read(apiProvider).createPairingCode();

  @override
  Widget build(BuildContext context) {
    final address = ref.watch(settingsProvider.select((s) => s.backendUrl));
    return AlertDialog(
      backgroundColor: UltronColors.surface,
      title: const Text('Pair a new device'),
      content: SizedBox(
        width: 420,
        child: FutureBuilder<PairingCode>(
          future: _code,
          builder: (context, snap) {
            if (snap.hasError) {
              final e = snap.error;
              return Text(e is ApiException ? e.message : 'Could not create a code');
            }
            final code = snap.data;
            if (code == null) return const LinearProgressIndicator(minHeight: 2);
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('On the new device, open ULTRON, choose "Pair with a code" and enter:'),
                const SizedBox(height: 16),
                Center(
                  child: SelectableText(
                    code.code,
                    key: const Key('pairing-code-display'),
                    style: const TextStyle(fontFamily: 'Orbitron', fontSize: 30, letterSpacing: 4),
                  ),
                ),
                const SizedBox(height: 8),
                Center(child: Text('Works once, for 10 minutes', style: Theme.of(context).textTheme.labelSmall)),
                const SizedBox(height: 16),
                _Row(
                  'Server address',
                  address,
                  detail: 'From a phone, use this PC\'s Wi-Fi address instead of 127.0.0.1.',
                ),
                if (code.shortFingerprint != null)
                  _Row(
                    'Security code',
                    code.shortFingerprint!,
                    color: UltronColors.success,
                    detail: 'The new device shows this when it connects. It must match exactly.',
                  )
                else
                  const _Row(
                    'Connection',
                    'Not encrypted (http)',
                    color: UltronColors.warning,
                    detail: 'Turn on HTTPS with `ultron-core tls-init` before pairing a phone over Wi-Fi.',
                  ),
              ],
            );
          },
        ),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Done'))],
    );
  }
}

final aiUsageProvider = FutureProvider<UsageInfo>((ref) => ref.watch(apiProvider).aiUsage(days: 7));

/// How many replies each AI source and model produced in the last 7 days.
class _UsageCard extends ConsumerWidget {
  const _UsageCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final usage = ref.watch(aiUsageProvider);
    return _Card(
      key: const Key('usage-card'),
      title: 'AI USAGE (7 DAYS)',
      icon: Icons.insights_outlined,
      trailing: IconButton(
        tooltip: 'Refresh',
        icon: const Icon(Icons.refresh, size: 18),
        onPressed: () => ref.invalidate(aiUsageProvider),
      ),
      child: usage.when(
        loading: () => const LinearProgressIndicator(minHeight: 2),
        error: (e, _) => Text(e is ApiException ? e.message : 'Could not load usage'),
        data: (u) => u.rows.isEmpty
            ? const Text('No replies yet.', style: TextStyle(color: UltronColors.textMuted))
            : Column(
                children: [
                  for (final r in u.rows)
                    _Row(
                      providerDisplayName(r.provider),
                      '${r.replies} replies${r.failed > 0 ? ' · ${r.failed} failed' : ''}',
                      color: r.kind == 'local' ? UltronColors.local : UltronColors.cloud,
                      detail: [
                        ?r.model,
                        if (r.inputTokens + r.outputTokens > 0) '${r.inputTokens + r.outputTokens} tokens',
                        if (r.fallbacks > 0) '${r.fallbacks} as fallback',
                        if (r.avgFirstTokenMs != null && r.avgDurationMs != null)
                          'first word ${(r.avgFirstTokenMs! / 1000).toStringAsFixed(1)} s, '
                              'done ${(r.avgDurationMs! / 1000).toStringAsFixed(1)} s (avg)',
                      ].join(' · '),
                    ),
                ],
              ),
      ),
    );
  }
}
