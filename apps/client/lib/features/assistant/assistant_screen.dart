import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/task_models.dart';
import '../../core/providers.dart';
import '../../core/theme/ultron_colors.dart';
import '../../widgets/glass_panel.dart';
import '../../widgets/ultron_background.dart';
import '../visualizer/chat_visualizer.dart';
import '../voice/voice_controller.dart';

const assistantGreeting = "Yes, I'm listening. What do you need?";

/// Whole phrases that end the assistant without doing anything ("stop",
/// "never mind", "go to sleep"). "Stop the music" is a command, not this.
final _dismiss = RegExp(
  r'^(?:(?:hey |ok )?ultron[,.!]?\s+)?(?:please\s+)?'
  r'(?:stop(?: listening| it| that)?|cancel(?: that| it)?|never ?mind|nothing|no thanks|'
  r'(?:go to )?sleep|goodbye|bye|exit|close)'
  r'(?:\s+please)?[.!]*$',
  caseSensitive: false,
);

bool isDismissCommand(String text) => _dismiss.hasMatch(text.trim());

enum AssistantStage { greeting, listening, thinking, answered, error }

/// What opens when ULTRON is invoked as the phone's assistant (or from the
/// app): greets, listens, runs the command or answers, and speaks the result.
class AssistantScreen extends ConsumerStatefulWidget {
  const AssistantScreen({super.key, this.greet = true});
  final bool greet;

  static Future<void> open(BuildContext context, {bool greet = true}) => Navigator.of(context).push(
    PageRouteBuilder<void>(
      opaque: false,
      transitionDuration: const Duration(milliseconds: 250),
      pageBuilder: (_, _, _) => AssistantScreen(greet: greet),
      transitionsBuilder: (_, animation, _, child) => FadeTransition(opacity: animation, child: child),
    ),
  );

  @override
  ConsumerState<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends ConsumerState<AssistantScreen> {
  AssistantStage stage = AssistantStage.greeting;
  String? heard;
  String? reply;
  TaskInfo? task;
  bool _busy = false;

  // Kept from initState: `ref` can't be used in dispose.
  late final VoiceController _voice;

  @override
  void initState() {
    super.initState();
    _voice = ref.read(voiceProvider.notifier);
    WidgetsBinding.instance.addPostFrameCallback((_) => _start());
  }

  @override
  void dispose() {
    // Closing the assistant stops it talking and listening.
    unawaited(_voice.stopSpeaking());
    unawaited(_voice.cancelListening());
    super.dispose();
  }

  Future<void> _start() async {
    if (widget.greet) {
      setState(() => stage = AssistantStage.greeting);
      await _voice.speak(assistantGreeting, private: false);
    }
    await _listen();
  }

  Future<void> _listen() async {
    if (!mounted) return;
    setState(() {
      stage = AssistantStage.listening;
      heard = null;
    });
    final text = await _voice.capture();
    if (!mounted) return;
    if (text == null || text.trim().isEmpty) {
      setState(() {
        stage = AssistantStage.error;
        reply = "I didn't catch that.";
      });
      return;
    }
    await submit(text);
  }

  Future<void> submit(String text) async {
    if (isDismissCommand(text)) {
      await _voice.speak('Okay.', private: false);
      if (mounted) Navigator.of(context).maybePop();
      return;
    }
    setState(() {
      heard = text;
      stage = AssistantStage.thinking;
      task = null;
    });
    try {
      final result = await ref.read(apiProvider).assistantCommand(text, wait: true, source: 'assistant');
      if (!mounted) return;
      setState(() {
        reply = result.message;
        task = result.task;
        stage = AssistantStage.answered;
      });
      await _voice.speak(result.message, private: false);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        reply = e.isNetwork ? "I can't reach ULTRON Core right now." : e.message;
        stage = AssistantStage.error;
      });
      await _voice.speak(reply!, private: false);
    }
  }

  Future<void> _decide({required bool approve, bool remember = false}) async {
    final current = task;
    if (current == null || _busy) return;
    setState(() => _busy = true);
    final api = ref.read(apiProvider);
    try {
      var updated = approve
          ? await api.approveTask(current.id, remember: remember)
          : await api.controlTask(current.id, 'reject');
      // Give the task a moment to finish so the answer can be spoken.
      for (var i = 0; i < 40 && approve && !updated.isFinished && !updated.needsApproval; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 500));
        updated = await api.task(current.id);
      }
      final message = !approve
          ? 'Okay, I won\'t do that.'
          : updated.status == 'completed'
          ? 'Done.'
          : updated.status == 'failed'
          ? "I couldn't finish that. ${updated.error ?? ''}".trim()
          : 'Working on it.';
      if (!mounted) return;
      setState(() {
        task = updated;
        reply = message;
      });
      await _voice.speak(message, private: false);
    } on ApiException catch (e) {
      if (mounted) setState(() => reply = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final voice = ref.watch(voiceProvider);
    final accent = Theme.of(context).colorScheme.primary;
    final status = switch (stage) {
      AssistantStage.greeting => assistantGreeting,
      AssistantStage.listening => voice.transcript.isEmpty ? 'Listening…' : voice.transcript,
      AssistantStage.thinking => 'Working on it…',
      AssistantStage.answered || AssistantStage.error => reply ?? '',
    };
    return Scaffold(
      key: const Key('assistant-screen'),
      backgroundColor: Colors.transparent,
      body: UltronBackground(
        child: SafeArea(
          child: Column(
            children: [
              Align(
                alignment: Alignment.topRight,
                child: IconButton(
                  key: const Key('assistant-close'),
                  tooltip: 'Close',
                  onPressed: () => Navigator.of(context).maybePop(),
                  icon: const Icon(Icons.close),
                ),
              ),
              const Spacer(),
              const ChatVisualizer(size: 220),
              const SizedBox(height: 28),
              if (heard != null)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                  child: Text(
                    '"$heard"',
                    key: const Key('assistant-heard'),
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: UltronColors.textSecondary, fontStyle: FontStyle.italic),
                  ),
                ),
              const SizedBox(height: 12),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 200),
                  child: Text(
                    status,
                    key: ValueKey('assistant-status-$stage-$status'),
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
              ),
              if (task != null && task!.needsApproval) ...[
                const SizedBox(height: 18),
                _ApprovalCard(task: task!, busy: _busy, onDecide: _decide),
              ],
              const Spacer(),
              Padding(
                padding: const EdgeInsets.only(bottom: 28),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    if (stage == AssistantStage.listening)
                      FilledButton.icon(
                        key: const Key('assistant-done'),
                        onPressed: _voice.finishCapture,
                        icon: const Icon(Icons.check),
                        label: const Text('Done'),
                      )
                    else
                      FilledButton.icon(
                        key: const Key('assistant-ask'),
                        onPressed: stage == AssistantStage.thinking ? null : _listen,
                        style: FilledButton.styleFrom(backgroundColor: accent),
                        icon: const Icon(Icons.mic),
                        label: const Text('Ask'),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ApprovalCard extends StatelessWidget {
  const _ApprovalCard({required this.task, required this.busy, required this.onDecide});
  final TaskInfo task;
  final bool busy;
  final Future<void> Function({required bool approve, bool remember}) onDecide;

  @override
  Widget build(BuildContext context) {
    final routine = task.waitingSteps.every((s) => s.risk == 'A');
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: GlassPanel(
        key: const Key('assistant-approval'),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final s in task.waitingSteps)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  children: [
                    Icon(
                      s.risk == 'A' ? Icons.task_alt : Icons.warning_amber_rounded,
                      size: 18,
                      color: s.risk == 'A' ? UltronColors.textSecondary : UltronColors.warning,
                    ),
                    const SizedBox(width: 8),
                    Expanded(child: Text(s.title)),
                  ],
                ),
              ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton(
                  key: const Key('assistant-approve'),
                  onPressed: busy ? null : () => onDecide(approve: true),
                  child: const Text('Do it'),
                ),
                if (routine)
                  OutlinedButton(
                    key: const Key('assistant-always'),
                    onPressed: busy ? null : () => onDecide(approve: true, remember: true),
                    child: const Text('Always allow'),
                  ),
                TextButton(
                  key: const Key('assistant-reject'),
                  onPressed: busy ? null : () => onDecide(approve: false),
                  child: const Text('No'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
