import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/task_models.dart';
import '../../core/auth/session.dart';
import '../../core/providers.dart';
import '../../core/theme/ultron_colors.dart';
import '../../widgets/glass_panel.dart';
import '../settings/ai_preferences_controller.dart';

const memoryKinds = {'preference': 'Preference', 'fact': 'Fact', 'project': 'Project', 'note': 'Note'};

final memoryQueryProvider = NotifierProvider<_Query, String>(_Query.new);

class _Query extends Notifier<String> {
  @override
  String build() => '';
  void set(String q) => state = q;
}

final memoriesProvider = AsyncNotifierProvider<MemoriesController, List<MemoryItem>>(MemoriesController.new);

class MemoriesController extends AsyncNotifier<List<MemoryItem>> {
  @override
  Future<List<MemoryItem>> build() async {
    if (ref.watch(sessionProvider) is! SignedIn) return const [];
    final q = ref.watch(memoryQueryProvider).trim();
    return ref.watch(apiProvider).memories(query: q.isEmpty ? null : q);
  }

  Future<void> add(String content, String kind, {bool pinned = false, bool private = false}) async {
    await ref.read(apiProvider).createMemory(content, kind: kind, pinned: pinned, private: private);
    ref.invalidateSelf();
  }

  Future<void> edit(MemoryItem m, {String? content, String? kind, bool? pinned, bool? private}) async {
    await ref.read(apiProvider).updateMemory(m.id, content: content, kind: kind, pinned: pinned, private: private);
    ref.invalidateSelf();
  }

  Future<void> remove(MemoryItem m) async {
    await ref.read(apiProvider).deleteMemory(m.id);
    state = AsyncData([
      for (final x in state.value ?? const <MemoryItem>[])
        if (x.id != m.id) x,
    ]);
  }

  Future<void> removeAll() async {
    await ref.read(apiProvider).deleteAllMemories();
    state = const AsyncData([]);
  }
}

/// What ULTRON remembers about you: see, search, add, edit, pin, export and
/// delete. Memories are used as background facts in chat (when enabled).
class MemoryPage extends ConsumerStatefulWidget {
  const MemoryPage({super.key});

  @override
  ConsumerState<MemoryPage> createState() => _MemoryPageState();
}

class _MemoryPageState extends ConsumerState<MemoryPage> {
  Timer? _debounce;

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  void _toast(String text) => ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text)));

  Future<void> _guard(Future<void> Function() action) async {
    try {
      await action();
    } on ApiException catch (e) {
      if (mounted) _toast(e.message);
    }
  }

  Future<void> _export() => _guard(() async {
    final data = await ref.read(apiProvider).exportMemories();
    await Clipboard.setData(ClipboardData(text: const JsonEncoder.withIndent('  ').convert(data)));
    _toast('Copied ${data['count']} memories to the clipboard as JSON.');
  });

  Future<void> _deleteAll() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: UltronColors.surface,
        title: const Text('Delete all memories?'),
        content: const Text('ULTRON will forget everything saved here. This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(
            key: const Key('confirm-delete-all'),
            style: FilledButton.styleFrom(backgroundColor: UltronColors.danger),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete all'),
          ),
        ],
      ),
    );
    if (ok == true) await _guard(ref.read(memoriesProvider.notifier).removeAll);
  }

  @override
  Widget build(BuildContext context) {
    final memories = ref.watch(memoriesProvider);
    final prefs = ref.watch(aiPreferencesProvider).value;
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 820),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
          children: [
            Row(
              children: [
                Expanded(child: Text('MEMORY', style: Theme.of(context).textTheme.headlineSmall)),
                FilledButton.icon(
                  key: const Key('add-memory'),
                  onPressed: () => _editDialog(null),
                  icon: const Icon(Icons.add),
                  label: const Text('Remember'),
                ),
                PopupMenuButton<String>(
                  key: const Key('memory-menu'),
                  onSelected: (v) => v == 'export' ? _export() : _deleteAll(),
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: 'export', child: Text('Export (copy JSON)')),
                    PopupMenuItem(value: 'delete', child: Text('Delete all…')),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 4),
            const Text(
              'Things ULTRON knows about you. They are given to the AI as background facts, never '
              'as instructions. Private memories are only used in private (local AI) chats.',
              style: TextStyle(color: UltronColors.textSecondary, fontSize: 12.5),
            ),
            if (prefs != null)
              SwitchListTile(
                key: const Key('memory-enabled'),
                contentPadding: EdgeInsets.zero,
                value: prefs.memoryEnabled,
                onChanged: (v) =>
                    _guard(() => ref.read(aiPreferencesProvider.notifier).save(prefs.copyWith(memoryEnabled: v))),
                title: const Text('Use memories in chat'),
              ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('memory-search'),
              decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search memories'),
              onChanged: (q) {
                _debounce?.cancel();
                _debounce = Timer(
                  const Duration(milliseconds: 350),
                  () => ref.read(memoryQueryProvider.notifier).set(q),
                );
              },
            ),
            const SizedBox(height: 14),
            ...memories.when(
              loading: () => [const LinearProgressIndicator(minHeight: 2)],
              error: (e, _) => [Text(e is ApiException ? e.message : 'Could not load memories')],
              data: (list) => list.isEmpty
                  ? [
                      const Padding(
                        padding: EdgeInsets.all(24),
                        child: Text(
                          'Nothing saved. Add something, or tell ULTRON "remember that …".',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: UltronColors.textSecondary),
                        ),
                      ),
                    ]
                  : [for (final m in list) _MemoryTile(memory: m, onEdit: () => _editDialog(m), guard: _guard)],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _editDialog(MemoryItem? existing) async {
    final draft = await showDialog<MemoryDraft>(
      context: context,
      builder: (context) => MemoryDialog(existing: existing),
    );
    if (draft == null || draft.content.isEmpty) return;
    final c = ref.read(memoriesProvider.notifier);
    await _guard(
      () => existing == null
          ? c.add(draft.content, draft.kind, pinned: draft.pinned, private: draft.private)
          : c.edit(existing, content: draft.content, kind: draft.kind, pinned: draft.pinned, private: draft.private),
    );
  }
}

class MemoryDraft {
  const MemoryDraft(this.content, this.kind, {required this.pinned, required this.private});
  final String content;
  final String kind;
  final bool pinned;
  final bool private;
}

/// Add or edit a memory. Owns its text field (disposed with the dialog).
class MemoryDialog extends StatefulWidget {
  const MemoryDialog({super.key, this.existing});
  final MemoryItem? existing;

  @override
  State<MemoryDialog> createState() => _MemoryDialogState();
}

class _MemoryDialogState extends State<MemoryDialog> {
  late final _text = TextEditingController(text: widget.existing?.content);
  late String _kind = widget.existing?.kind ?? 'note';
  late bool _pinned = widget.existing?.pinned ?? false;
  late bool _private = widget.existing?.isPrivate ?? false;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    backgroundColor: UltronColors.surface,
    title: Text(widget.existing == null ? 'Remember' : 'Edit memory'),
    content: SizedBox(
      width: 460,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            key: const Key('memory-text'),
            controller: _text,
            autofocus: true,
            maxLines: 4,
            minLines: 2,
            maxLength: 2000,
            decoration: const InputDecoration(hintText: 'e.g. My exams start on 2 December'),
          ),
          DropdownButtonFormField<String>(
            key: const Key('memory-kind'),
            initialValue: _kind,
            items: [for (final e in memoryKinds.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
            onChanged: (v) => setState(() => _kind = v ?? _kind),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: _pinned,
            onChanged: (v) => setState(() => _pinned = v),
            title: const Text('Pinned (always used)'),
          ),
          SwitchListTile(
            key: const Key('memory-private'),
            contentPadding: EdgeInsets.zero,
            value: _private,
            onChanged: (v) => setState(() => _private = v),
            title: const Text('Private (local AI only)'),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
      FilledButton(
        key: const Key('memory-save'),
        onPressed: () =>
            Navigator.pop(context, MemoryDraft(_text.text.trim(), _kind, pinned: _pinned, private: _private)),
        child: const Text('Save'),
      ),
    ],
  );
}

class _MemoryTile extends ConsumerWidget {
  const _MemoryTile({required this.memory, required this.onEdit, required this.guard});
  final MemoryItem memory;
  final VoidCallback onEdit;
  final Future<void> Function(Future<void> Function()) guard;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = ref.read(memoriesProvider.notifier);
    return Padding(
      key: Key('memory-${memory.id}'),
      padding: const EdgeInsets.only(bottom: 10),
      child: GlassPanel(
        padding: const EdgeInsets.fromLTRB(16, 10, 6, 10),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(memory.content),
                  const SizedBox(height: 4),
                  Text(
                    [
                      memoryKinds[memory.kind] ?? memory.kind,
                      if (memory.isPrivate) 'private',
                      if (memory.source != 'user') 'saved by a task',
                      if (memory.lastUsedAt != null) 'last used ${memory.lastUsedAt.toString().substring(0, 10)}',
                    ].join(' · '),
                    style: const TextStyle(fontSize: 11.5, color: UltronColors.textMuted),
                  ),
                ],
              ),
            ),
            if (memory.isPrivate) const Icon(Icons.lock, size: 16, color: UltronColors.local),
            IconButton(
              key: Key('pin-${memory.id}'),
              tooltip: memory.pinned ? 'Unpin' : 'Pin (always use)',
              onPressed: () => guard(() => c.edit(memory, pinned: !memory.pinned)),
              icon: Icon(memory.pinned ? Icons.push_pin : Icons.push_pin_outlined, size: 20),
            ),
            IconButton(tooltip: 'Edit', onPressed: onEdit, icon: const Icon(Icons.edit_outlined, size: 20)),
            IconButton(
              key: Key('delete-memory-${memory.id}'),
              tooltip: 'Delete',
              onPressed: () => guard(() => c.remove(memory)),
              icon: const Icon(Icons.delete_outline, size: 20),
            ),
          ],
        ),
      ),
    );
  }
}
