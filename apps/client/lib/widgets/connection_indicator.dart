import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/status/system_status.dart';
import '../core/theme/ultron_colors.dart';

/// Backend link plus which AI sources are available right now.
class ConnectionIndicator extends ConsumerWidget {
  const ConnectionIndicator({super.key, this.compact = false});
  final bool compact;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(systemStatusProvider);
    final (label, color) = switch (s.link) {
      BackendLink.checking => ('Connecting…', UltronColors.textSecondary),
      BackendLink.online => ('Core online', UltronColors.success),
      BackendLink.degraded => ('Core degraded', UltronColors.warning),
      BackendLink.offline => ('Core offline', UltronColors.danger),
    };
    final online = s.link == BackendLink.online || s.link == BackendLink.degraded;
    final chips = [
      _SourceChip(label: 'CLOUD', active: online && s.cloudAvailable, color: UltronColors.cloud),
      _SourceChip(label: 'LOCAL', active: online && s.localAvailable, color: UltronColors.local),
    ];
    final link = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        StatusDot(color: color),
        const SizedBox(width: 8),
        Text(label, style: const TextStyle(fontSize: 12, color: UltronColors.textSecondary)),
      ],
    );
    return Semantics(
      label:
          '$label. Cloud AI ${online && s.cloudAvailable ? 'available' : 'unavailable'}. '
          'Local AI ${online && s.localAvailable ? 'available' : 'unavailable'}.',
      child: compact
          ? Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                StatusDot(color: color),
                const SizedBox(width: 6),
                ...chips,
              ],
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                link,
                const SizedBox(height: 10),
                Wrap(spacing: 6, children: chips),
              ],
            ),
    );
  }
}

class StatusDot extends StatelessWidget {
  const StatusDot({super.key, required this.color, this.size = 8});
  final Color color;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
    width: size,
    height: size,
    decoration: BoxDecoration(
      shape: BoxShape.circle,
      color: color,
      boxShadow: [BoxShadow(color: color.withValues(alpha: 0.7), blurRadius: 8)],
    ),
  );
}

class _SourceChip extends StatelessWidget {
  const _SourceChip({required this.label, required this.active, required this.color});
  final String label;
  final bool active;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final c = active ? color : UltronColors.textMuted;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: c.withValues(alpha: 0.6)),
        color: active ? c.withValues(alpha: 0.12) : Colors.transparent,
      ),
      child: Text(
        label,
        style: TextStyle(fontSize: 10, letterSpacing: 1.4, color: c, fontWeight: FontWeight.w600),
      ),
    );
  }
}
