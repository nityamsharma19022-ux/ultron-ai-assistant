import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/models.dart';
import '../../core/theme/ultron_colors.dart';
import 'chat_controller.dart';

class ConversationList extends ConsumerWidget {
  const ConversationList({super.key, this.onSelected});

  /// Called after a conversation is opened or a new one started (closes the
  /// phone sheet).
  final VoidCallback? onSelected;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(conversationsProvider);
    final current = ref.watch(chatProvider.select((s) => s.conversation?.id));
    final accent = Theme.of(context).colorScheme.primary;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
          child: OutlinedButton.icon(
            key: const Key('new-chat'),
            onPressed: () {
              ref.read(chatProvider.notifier).newConversation();
              onSelected?.call();
            },
            icon: const Icon(Icons.add),
            label: const Text('New conversation'),
          ),
        ),
        Expanded(
          child: list.when(
            loading: () => const Center(child: CircularProgressIndicator(strokeWidth: 2)),
            error: (e, _) => Center(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(e is ApiException ? e.message : 'Could not load conversations', textAlign: TextAlign.center),
                    TextButton(
                      onPressed: () => ref.read(conversationsProvider.notifier).reload(),
                      child: const Text('Retry'),
                    ),
                  ],
                ),
              ),
            ),
            data: (items) => items.isEmpty
                ? const Center(
                    child: Text('No conversations yet', style: TextStyle(color: UltronColors.textMuted)),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    itemCount: items.length,
                    itemBuilder: (context, i) => _Tile(
                      conversation: items[i],
                      selected: items[i].id == current,
                      accent: accent,
                      onTap: () {
                        ref.read(chatProvider.notifier).open(items[i].id);
                        onSelected?.call();
                      },
                      onDelete: () => _confirmDelete(context, ref, items[i]),
                    ),
                  ),
          ),
        ),
      ],
    );
  }

  Future<void> _confirmDelete(BuildContext context, WidgetRef ref, Conversation c) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: UltronColors.surface,
        title: const Text('Delete conversation?'),
        content: Text('"${c.displayTitle}" will be removed.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(conversationsProvider.notifier).delete(c.id);
      if (ref.read(chatProvider).conversation?.id == c.id) ref.read(chatProvider.notifier).newConversation();
    } on ApiException catch (e) {
      if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }
}

class _Tile extends StatelessWidget {
  const _Tile({
    required this.conversation,
    required this.selected,
    required this.accent,
    required this.onTap,
    required this.onDelete,
  });
  final Conversation conversation;
  final bool selected;
  final Color accent;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 4),
    child: Material(
      color: selected ? accent.withValues(alpha: 0.12) : Colors.transparent,
      borderRadius: BorderRadius.circular(12),
      child: ListTile(
        key: Key('conversation-${conversation.id}'),
        dense: true,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        onTap: onTap,
        leading: Icon(
          conversation.isPrivate ? Icons.lock_outline : Icons.chat_bubble_outline,
          size: 18,
          color: conversation.isPrivate ? UltronColors.local : UltronColors.textSecondary,
        ),
        title: Text(conversation.displayTitle, maxLines: 1, overflow: TextOverflow.ellipsis),
        subtitle: Text(
          _ago(conversation.updatedAt),
          style: const TextStyle(fontSize: 11, color: UltronColors.textMuted),
        ),
        trailing: IconButton(
          tooltip: 'Delete',
          iconSize: 18,
          icon: const Icon(Icons.delete_outline, color: UltronColors.textMuted),
          onPressed: onDelete,
        ),
      ),
    ),
  );

  static String _ago(DateTime t) {
    final d = DateTime.now().difference(t);
    if (d.inMinutes < 1) return 'just now';
    if (d.inHours < 1) return '${d.inMinutes} min ago';
    if (d.inDays < 1) return '${d.inHours} h ago';
    if (d.inDays < 7) return '${d.inDays} d ago';
    return '${t.year}-${t.month.toString().padLeft(2, '0')}-${t.day.toString().padLeft(2, '0')}';
  }
}
