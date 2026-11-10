import 'package:flutter/material.dart';

import '../core/theme/ultron_colors.dart';

/// "LOCAL · ollama · qwen3.5:4b" / "CLOUD · groq · model" label for a reply.
class AiSourceBadge extends StatelessWidget {
  const AiSourceBadge({super.key, required this.kind, this.provider, this.model, this.fallback = false});
  final String kind;
  final String? provider;
  final String? model;
  final bool fallback;

  @override
  Widget build(BuildContext context) {
    final local = kind == 'local';
    final color = local ? UltronColors.local : UltronColors.cloud;
    final parts = [?provider, ?model];
    return Semantics(
      label:
          '${local ? 'Local' : 'Cloud'} AI${parts.isEmpty ? '' : ', ${parts.join(', ')}'}${fallback ? ', fallback' : ''}',
      child: Wrap(
        spacing: 6,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: color.withValues(alpha: 0.5)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(local ? Icons.memory : Icons.cloud_outlined, size: 11, color: color),
                const SizedBox(width: 4),
                Text(
                  local ? 'LOCAL' : 'CLOUD',
                  style: TextStyle(fontSize: 10, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: color),
                ),
              ],
            ),
          ),
          if (parts.isNotEmpty)
            Text(parts.join(' · '), style: const TextStyle(fontSize: 11, color: UltronColors.textMuted)),
          if (fallback)
            const Tooltip(
              message: 'The preferred AI was unavailable, so ULTRON switched to this one.',
              child: Text('fallback', style: TextStyle(fontSize: 11, color: UltronColors.warning)),
            ),
        ],
      ),
    );
  }
}
