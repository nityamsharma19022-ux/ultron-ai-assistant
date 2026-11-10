import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/ultron_colors.dart';
import '../chat/chat_controller.dart';
import 'voice_controller.dart';

/// Mic button in the composer. Tap to talk, tap again to send. While a
/// reply is being read aloud it becomes a "stop reading" button.
class VoiceButton extends ConsumerWidget {
  const VoiceButton({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final voice = ref.watch(voiceProvider);
    final private = ref.watch(chatProvider.select((s) => s.isPrivate));
    final onDevice = ref.watch(speechInputProvider).recognisesOnDevice;
    final controller = ref.read(voiceProvider.notifier);
    final accent = Theme.of(context).colorScheme.primary;

    if (voice.speaking) {
      return IconButton(
        key: const Key('stop-speaking'),
        tooltip: 'Stop reading aloud',
        onPressed: controller.stopSpeaking,
        icon: Icon(Icons.volume_off_outlined, color: accent),
      );
    }
    if (voice.listening) {
      return IconButton.filled(
        key: const Key('mic-button'),
        tooltip: 'Stop and send',
        onPressed: controller.toggleListening,
        style: IconButton.styleFrom(backgroundColor: UltronColors.danger.withValues(alpha: 0.85)),
        icon: const Icon(Icons.mic),
      );
    }
    final blocked = private && !onDevice;
    return IconButton(
      key: const Key('mic-button'),
      tooltip: blocked ? 'Voice input is off in private conversations on this device' : 'Speak',
      // Still tappable when blocked, so the user gets the explanation.
      onPressed: controller.toggleListening,
      icon: Icon(blocked ? Icons.mic_off_outlined : Icons.mic_none, color: blocked ? UltronColors.textMuted : null),
    );
  }
}

/// Shown above the composer while listening: the words heard so far and a
/// cancel button.
class ListeningBar extends ConsumerWidget {
  const ListeningBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final voice = ref.watch(voiceProvider);
    final accent = Theme.of(context).colorScheme.primary;
    return AnimatedSize(
      duration: const Duration(milliseconds: 200),
      alignment: Alignment.bottomCenter,
      child: !voice.listening
          ? const SizedBox(width: double.infinity)
          : Container(
              key: const Key('listening-bar'),
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.fromLTRB(14, 8, 6, 8),
              decoration: BoxDecoration(
                color: accent.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: accent.withValues(alpha: 0.3)),
              ),
              child: Row(
                children: [
                  Icon(Icons.graphic_eq, size: 18, color: accent),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      voice.transcribing
                          ? 'Transcribing…'
                          : voice.transcript.isEmpty
                          ? 'Listening… tap the mic again to send'
                          : voice.transcript,
                      key: const Key('transcript'),
                      style: TextStyle(
                        color: voice.transcript.isEmpty ? UltronColors.textSecondary : UltronColors.textPrimary,
                      ),
                    ),
                  ),
                  IconButton(
                    key: const Key('cancel-listening'),
                    tooltip: 'Cancel',
                    onPressed: ref.read(voiceProvider.notifier).cancelListening,
                    icon: const Icon(Icons.close, size: 18),
                  ),
                ],
              ),
            ),
    );
  }
}
