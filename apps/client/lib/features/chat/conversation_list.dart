import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/command_models.dart';
import '../../core/api/models.dart';
import '../../core/providers.dart';
import '../../core/theme/ultron_colors.dart';
import 'chat_controller.dart';

class ConversationList extends ConsumerStatefulWidget {
  const ConversationList({super.key, this.onSelected});

  /// Called after a conversation is opened or a new one started (closes the
  /// phone sheet).
  final VoidCallback? onSelected;

  @override
  ConsumerState<ConversationList> createState() => _ConversationListState();
}

class _ConversationListState extends ConsumerState<ConversationList> {
  final _search = TextEditingController();
  Timer? _debounce;
  String _query = '';
  List<SearchHit>? _hits;
  String? _searchError;
  int _searchId = 0;

  VoidCallback? get onSelected => widget.onSelected;

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _onQuery(String value) {
    _debounce?.cancel();
    setState(() => _query = value.trim());
    if (_query.isEmpty) {
      setState(() => _hits = null);
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 350), _runSearch);
  }

  Future<void> _runSearch() async {
    final id = ++_searchId;
    try {
      final hits = await ref.read(apiProvider).searchConversations(_query);
      if (mounted && id == _searchId) {
        setState(() {
          _hits = hits;
          _searchError = null;
        });
      }
    } on ApiException catch (e) {
      if (mounted && id == _searchId) setState(() => _searchError = e.message);
    }
  }

  Widget _results(Color accent) {
    if (_searchError != null) return Center(child: Text(_searchError!, textAlign: TextAlign.center));
    final hits = _hits;
    if (hits == null) return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    if (hits.isEmpty) {
      return const Center(
        child: Text('Nothing found', style: TextStyle(color: UltronColors.textMuted)),
      );
    }
    return ListView(
      key: const Key('search-results'),
      padding: const EdgeInsets.symmetric(horizontal: 8),
      children: [
        for (final h in hits)
          ListTile(
            key: Key('hit-${h.messageId}'),
            dense: true,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            leading: Icon(
              h.role == 'user' ? Icons.person_outline : Icons.auto_awesome,
              size: 18,
              color: h.isPrivate ? UltronColors.local : UltronColors.textSecondary,
            ),
            title: Text(h.conversationTitle ?? 'Conversation', maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle: Text.rich(_highlight(h.snippet, accent), maxLines: 3, overflow: TextOverflow.ellipsis),
            onTap: () {
              ref.read(chatProvider.notifier).open(h.conversationId);
              onSelected?.call();
            },
          ),
      ],
    );
  }

  /// Snippets mark matches with « and ».
  static TextSpan _highlight(String snippet, Color accent) {
    final spans = <TextSpan>[];
    final re = RegExp('«([^»]*)»');
    var last = 0;
    for (final m in re.allMatches(snippet)) {
      if (m.start > last) spans.add(TextSpan(text: snippet.substring(last, m.start)));
      spans.add(
        TextSpan(
          text: m.group(1),
          style: TextStyle(color: accent, fontWeight: FontWeight.w600),
        ),
      );
      last = m.end;
    }
    if (last < snippet.length) spans.add(TextSpan(text: snippet.substring(last)));
    return TextSpan(
      style: const TextStyle(fontSize: 12, color: UltronColors.textSecondary),
      children: spans,
    );
  }

  @override
  Widget build(BuildContext context) {
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
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          child: TextField(
            key: const Key('conversation-search'),
            controller: _search,
            onChanged: _onQuery,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              isDense: true,
              hintText: 'Search all conversations',
              prefixIcon: const Icon(Icons.search, size: 18),
              suffixIcon: _query.isEmpty
                  ? null
                  : IconButton(
                      tooltip: 'Clear',
                      icon: const Icon(Icons.close, size: 16),
                      onPressed: () {
                        _search.clear();
                        _onQuery('');
                      },
                    ),
            ),
          ),
        ),
        Expanded(
          child: _query.isNotEmpty
              ? _results(accent)
              : list.when(
                  loading: () => const Center(child: CircularProgressIndicator(strokeWidth: 2)),
                  error: (e, _) => Center(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            e is ApiException ? e.message : 'Could not load conversations',
                            textAlign: TextAlign.center,
                          ),
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
                            onDelete: () => _confirmDelete(context, items[i]),
                          ),
                        ),
                ),
        ),
      ],
    );
  }

  Future<void> _confirmDelete(BuildContext context, Conversation c) async {
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
          [?conversation.project, _ago(conversation.updatedAt)].join(' · '),
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
