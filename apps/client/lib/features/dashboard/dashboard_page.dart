import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/models.dart';
import '../../core/auth/session.dart';
import '../../core/status/system_status.dart';
import '../../core/theme/ultron_colors.dart';
import '../../widgets/connection_indicator.dart';
import '../../widgets/glass_panel.dart';
import '../visualizer/chat_visualizer.dart';
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
        ];
        return RefreshIndicator(
          onRefresh: () async {
            await ref.read(systemStatusProvider.notifier).refresh();
            ref.invalidate(devicesProvider);
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
                    Expanded(child: Column(children: [cards[0], const SizedBox(height: 16), cards[1]])),
                    const SizedBox(width: 16),
                    Expanded(child: Column(children: [cards[2], const SizedBox(height: 16), cards[3]])),
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
                checked == null ? 'Checking…' : 'Last checked ${_time(checked)} · refreshes every 20 s',
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

String _time(DateTime t) =>
    '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}:${t.second.toString().padLeft(2, '0')}';

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

class _ProvidersCard extends StatelessWidget {
  const _ProvidersCard({required this.status});
  final SystemStatus status;

  @override
  Widget build(BuildContext context) {
    final ai = status.ai;
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
                for (final p in ai.providers)
                  _Row(
                    p.name,
                    _providerLabel(p),
                    color: _checkColor(p.status),
                    detail: [p.kind, ?p.model, ?p.reason].join(' · '),
                  ),
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
                  d.lastSeenAt == null ? d.platform : '${d.platform} · last active ${_date(d.lastSeenAt!)}',
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

  static String _date(DateTime t) =>
      '${t.year}-${t.month.toString().padLeft(2, '0')}-${t.day.toString().padLeft(2, '0')} ${_time(t).substring(0, 5)}';

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
