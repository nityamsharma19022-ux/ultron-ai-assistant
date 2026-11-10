import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/settings/app_settings.dart';
import '../../core/status/system_status.dart';
import '../chat/chat_controller.dart';
import 'ai_visualizer.dart';
import '../voice/voice_controller.dart';
import 'visualizer_mode.dart';

/// The visualizer wired to the app: reply phase, AI source, backend link,
/// voice (listening, speaking, mic level) and the motion setting.
class ChatVisualizer extends ConsumerWidget {
  const ChatVisualizer({super.key, required this.size});
  final double size;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chat = ref.watch(chatProvider);
    final link = ref.watch(systemStatusProvider.select((s) => s.link));
    final motion = ref.watch(settingsProvider.select((s) => s.motion));
    final voice = ref.watch(voiceProvider);
    final mode = visualizerModeFor(phase: chat.phase, link: link, listening: voice.listening, speaking: voice.speaking);
    return AiVisualizer(
      mode: mode,
      color: visualizerColor(mode, Theme.of(context).colorScheme.primary, aiKind: chat.phaseKind),
      size: size,
      level: voice.listening ? voice.level : 0,
      motion: motion,
    );
  }
}
