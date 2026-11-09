import 'package:flutter/material.dart';

import '../../core/theme/ultron_colors.dart';
import 'chat_state.dart';

/// One line describing what ULTRON is doing right now.
class PhaseIndicator extends StatelessWidget {
  const PhaseIndicator({super.key, required this.state});
  final ChatState state;

  static String describe(ChatState s) {
    final model = s.phaseModel ?? s.phaseProvider;
    final where = s.phaseKind == 'local' ? 'local AI' : (s.phaseKind == 'cloud' ? 'cloud AI' : 'AI');
    return switch (s.phase) {
      ReplyPhase.idle => '',
      ReplyPhase.routing => 'Choosing the best AI…',
      ReplyPhase.loadingModel => 'Loading local model${model == null ? '' : ' $model'}… (first reply can take a while)',
      ReplyPhase.waiting => 'Waiting for ${model ?? where}…',
      ReplyPhase.generating => 'Generating with $where${model == null ? '' : ' · $model'}',
    };
  }

  @override
  Widget build(BuildContext context) {
    final busy = state.busy;
    final color = state.phaseKind == 'local'
        ? UltronColors.local
        : state.phaseKind == 'cloud'
        ? UltronColors.cloud
        : Theme.of(context).colorScheme.primary;
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 250),
      child: busy
          ? Padding(
              key: ValueKey(state.phase),
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
              child: Row(
                children: [
                  SizedBox(
                    width: 12,
                    height: 12,
                    child: CircularProgressIndicator(strokeWidth: 1.6, color: color),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      describe(state),
                      key: const Key('phase-text'),
                      style: const TextStyle(fontSize: 12.5, color: UltronColors.textSecondary),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
            )
          : const SizedBox(key: ValueKey('idle'), height: 0),
    );
  }
}
