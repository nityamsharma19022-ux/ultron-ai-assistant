import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/models.dart';
import '../../core/status/system_status.dart';
import '../../core/theme/ultron_colors.dart';
import '../shell/app_shell.dart';
import 'chat_controller.dart';
import 'chat_state.dart';
import 'composer.dart';
import 'conversation_list.dart';
import 'message_bubble.dart';
import 'phase_indicator.dart';

/// Builds the large visualizer shown above an empty conversation; replaced
/// in the visualizer increment.
typedef HeroBuilder = Widget Function(BuildContext context, ChatState state, double size);

class ChatPage extends ConsumerWidget {
  const ChatPage({super.key, this.heroBuilder, this.headerOrbBuilder, this.composerLeading});

  final HeroBuilder? heroBuilder;
  final HeroBuilder? headerOrbBuilder;
  final Widget? composerLeading;

  @override
  Widget build(BuildContext context, WidgetRef ref) => LayoutBuilder(
    builder: (context, c) {
      final wide = c.maxWidth >= kWideLayoutBreakpoint - 236; // content width beside the sidebar
      final chat = _ChatView(
        heroBuilder: heroBuilder,
        headerOrbBuilder: headerOrbBuilder,
        composerLeading: composerLeading,
        showListButton: !wide,
      );
      if (!wide) return chat;
      return Row(
        children: [
          Container(
            key: const Key('conversation-panel'),
            width: 280,
            decoration: BoxDecoration(
              border: Border(right: BorderSide(color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.10))),
            ),
            child: const ConversationList(),
          ),
          Expanded(child: chat),
        ],
      );
    },
  );
}

class _ChatView extends ConsumerWidget {
  const _ChatView({
    required this.heroBuilder,
    required this.headerOrbBuilder,
    required this.composerLeading,
    required this.showListButton,
  });
  final HeroBuilder? heroBuilder;
  final HeroBuilder? headerOrbBuilder;
  final Widget? composerLeading;
  final bool showListButton;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(chatProvider);
    final chat = ref.read(chatProvider.notifier);
    final empty = state.messages.isEmpty && !state.loading;

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 900),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
          child: Column(
            children: [
              _Header(state: state, showListButton: showListButton, orbBuilder: headerOrbBuilder),
              Expanded(
                child: state.loading
                    ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
                    : state.loadError != null
                    ? Center(
                        child: Text(state.loadError!, style: const TextStyle(color: UltronColors.danger)),
                      )
                    : empty
                    ? _EmptyState(state: state, heroBuilder: heroBuilder, onPick: chat.send)
                    : ListView.builder(
                        key: const Key('message-list'),
                        reverse: true,
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        itemCount: state.messages.length,
                        itemBuilder: (context, i) {
                          final m = state.messages[state.messages.length - 1 - i];
                          return MessageBubble(
                            key: ValueKey(m.id),
                            message: m,
                            onRetry: m.status == MessageStatus.failed && !state.busy ? () => chat.retry(m.id) : null,
                          );
                        },
                      ),
              ),
              PhaseIndicator(state: state),
              const SizedBox(height: 6),
              Composer(
                busy: state.busy,
                onSend: chat.send,
                onStop: chat.cancel,
                leading: composerLeading,
                hint: state.isPrivate ? 'Private message (local AI only)…' : 'Message ULTRON…',
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Header extends ConsumerWidget {
  const _Header({required this.state, required this.showListButton, required this.orbBuilder});
  final ChatState state;
  final bool showListButton;
  final HeroBuilder? orbBuilder;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chat = ref.read(chatProvider.notifier);
    final privateSupported = ref.watch(systemStatusProvider.select((s) => s.ai?.privateConversationsSupported ?? true));
    final title = state.conversation?.displayTitle ?? 'New conversation';
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        children: [
          if (showListButton)
            IconButton(
              key: const Key('open-conversations'),
              tooltip: 'Conversations',
              icon: const Icon(Icons.menu_open),
              onPressed: () => showModalBottomSheet<void>(
                context: context,
                backgroundColor: UltronColors.surface,
                showDragHandle: true,
                isScrollControlled: true,
                builder: (sheet) => SizedBox(
                  height: MediaQuery.sizeOf(context).height * 0.7,
                  child: ConversationList(onSelected: () => Navigator.pop(sheet)),
                ),
              ),
            ),
          if (orbBuilder != null && !(state.messages.isEmpty && !state.loading)) ...[
            orbBuilder!(context, state, 34),
            const SizedBox(width: 10),
          ],
          Expanded(
            child: Text(
              title,
              key: const Key('chat-title'),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.titleLarge?.copyWith(letterSpacing: 0.6),
            ),
          ),
          _PrivacyControl(
            isPrivate: state.isPrivate,
            started: state.conversation != null,
            supported: privateSupported,
            onChanged: (v) async {
              if (state.conversation == null) {
                chat.setNewChatPrivate(v);
              } else if (v) {
                try {
                  await chat.makePrivate();
                } on ApiException catch (e) {
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
                  }
                }
              }
            },
          ),
          if (state.conversation != null)
            IconButton(
              key: const Key('header-new-chat'),
              tooltip: 'New conversation',
              icon: const Icon(Icons.add_comment_outlined),
              onPressed: () => chat.newConversation(),
            ),
        ],
      ),
    );
  }
}

/// Private = local AI only. Can be switched on any time, never off.
class _PrivacyControl extends StatelessWidget {
  const _PrivacyControl({
    required this.isPrivate,
    required this.started,
    required this.supported,
    required this.onChanged,
  });
  final bool isPrivate;
  final bool started;
  final bool supported;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final locked = isPrivate && started;
    final tip = locked
        ? 'Private: this conversation only uses local AI and stays on your machine.'
        : isPrivate
        ? 'Private: local AI only. Tap to make this a normal conversation.'
        : supported
        ? 'Make private: local AI only, never sent to the cloud.'
        : 'Private conversations need local AI, which is not available right now.';
    return Tooltip(
      message: tip,
      child: FilterChip(
        key: const Key('private-toggle'),
        selected: isPrivate,
        showCheckmark: false,
        avatar: Icon(
          isPrivate ? Icons.lock : Icons.lock_open,
          size: 16,
          color: isPrivate ? UltronColors.local : UltronColors.textSecondary,
        ),
        label: Text(isPrivate ? 'Private' : 'Standard'),
        selectedColor: UltronColors.local.withValues(alpha: 0.14),
        side: BorderSide(color: (isPrivate ? UltronColors.local : UltronColors.panelBorder).withValues(alpha: 0.6)),
        onSelected: locked ? null : onChanged,
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.state, required this.heroBuilder, required this.onPick});
  final ChatState state;
  final HeroBuilder? heroBuilder;
  final ValueChanged<String> onPick;

  static const suggestions = [
    'Plan my day in three steps',
    'Explain how local and cloud AI differ',
    'Draft a short, polite reminder email',
  ];

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, c) {
      final size = (c.maxHeight * 0.45).clamp(120.0, 300.0);
      return SingleChildScrollView(
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: c.maxHeight),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (heroBuilder != null) heroBuilder!(context, state, size),
              const SizedBox(height: 18),
              Text(
                state.isPrivate ? 'Private conversation' : 'How can I help?',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 8),
              Text(
                state.isPrivate
                    ? 'Answered by local AI only. Nothing is sent to the cloud.'
                    : 'Cloud AI first, local AI when you\'re offline.',
                style: const TextStyle(color: UltronColors.textSecondary),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 20),
              Wrap(
                alignment: WrapAlignment.center,
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final s in suggestions)
                    ActionChip(
                      label: Text(s),
                      onPressed: () => onPick(s),
                      side: BorderSide(color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.3)),
                    ),
                ],
              ),
            ],
          ),
        ),
      );
    },
  );
}
