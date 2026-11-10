import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/task_models.dart';
import '../../core/auth/session.dart';
import '../../core/providers.dart';
import '../../core/theme/ultron_colors.dart';
import '../../widgets/glass_panel.dart';
import '../chat/chat_controller.dart';
import '../shell/sections.dart';

const supportedDocumentTypes = ['pdf', 'docx', 'xlsx', 'txt', 'md', 'csv', 'json'];

/// A file the user picked.
class PickedFile {
  const PickedFile(this.name, this.bytes);
  final String name;
  final List<int> bytes;
}

/// Where files come from (the system file picker; tests use a fake).
abstract class FileSource {
  Future<PickedFile?> pick();
}

class SystemFileSource implements FileSource {
  const SystemFileSource();
  @override
  Future<PickedFile?> pick() async {
    final files = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: supportedDocumentTypes);
    if (files.isEmpty) return null;
    final f = files.first;
    return PickedFile(f.name, await f.readAsBytes());
  }
}

final fileSourceProvider = Provider<FileSource>((ref) => const SystemFileSource());

final documentsProvider = AsyncNotifierProvider<DocumentsController, List<DocumentInfo>>(DocumentsController.new);

class DocumentsController extends AsyncNotifier<List<DocumentInfo>> {
  @override
  Future<List<DocumentInfo>> build() async {
    if (ref.watch(sessionProvider) is! SignedIn) return const [];
    return ref.watch(apiProvider).documents();
  }

  /// Picks and uploads a file; null if the user cancelled.
  Future<DocumentInfo?> pickAndUpload({bool private = false}) async {
    final file = await ref.read(fileSourceProvider).pick();
    if (file == null) return null;
    final doc = await ref.read(apiProvider).uploadDocument(file.name, file.bytes, private: private);
    final list = [
      for (final d in state.value ?? const <DocumentInfo>[])
        if (d.id != doc.id) d,
    ];
    state = AsyncData([doc, ...list]);
    return doc;
  }

  Future<void> remove(DocumentInfo doc) async {
    await ref.read(apiProvider).deleteDocument(doc.id);
    ref.read(chatProvider.notifier).detach(doc.id);
    state = AsyncData([
      for (final d in state.value ?? const <DocumentInfo>[])
        if (d.id != doc.id) d,
    ]);
  }
}

IconData documentIcon(String kind) => switch (kind) {
  'pdf' => Icons.picture_as_pdf_outlined,
  'docx' => Icons.description_outlined,
  'sheet' => Icons.table_chart_outlined,
  _ => Icons.article_outlined,
};

void _toast(BuildContext context, String text) => ScaffoldMessenger.of(context)
  ..hideCurrentSnackBar()
  ..showSnackBar(SnackBar(content: Text(text)));

/// Documents tab: upload, list, ask about, delete.
class DocumentsTab extends ConsumerStatefulWidget {
  const DocumentsTab({super.key});

  @override
  ConsumerState<DocumentsTab> createState() => _DocumentsTabState();
}

class _DocumentsTabState extends ConsumerState<DocumentsTab> {
  bool _uploading = false;
  bool _private = false;

  Future<void> _upload() async {
    setState(() => _uploading = true);
    try {
      final doc = await ref.read(documentsProvider.notifier).pickAndUpload(private: _private);
      if (doc != null && mounted) {
        _toast(context, doc.reused ? '${doc.name} was already added.' : 'Added ${doc.name} (${doc.chunkCount} parts).');
      }
    } on ApiException catch (e) {
      if (mounted) _toast(context, e.message);
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  void _ask(DocumentInfo doc) {
    final chat = ref.read(chatProvider);
    if (doc.isPrivate && !chat.isPrivate) {
      ref.read(chatProvider.notifier).newConversation(private: true);
    }
    ref.read(chatProvider.notifier).attach(doc);
    ref.read(sectionProvider.notifier).select(AppSection.chat);
  }

  @override
  Widget build(BuildContext context) {
    final docs = ref.watch(documentsProvider);
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 820),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
          children: [
            GlassPanel(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Add PDFs, Word and Excel files, or text and Markdown. ULTRON reads them so you can ask '
                    'questions or use them in tasks. Text inside documents is treated as information, never as '
                    'instructions. Images, scanned PDFs and audio can\'t be read yet.',
                    style: TextStyle(color: UltronColors.textSecondary, fontSize: 12.5),
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      FilledButton.icon(
                        key: const Key('upload-document'),
                        onPressed: _uploading ? null : _upload,
                        icon: _uploading
                            ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.upload_file),
                        label: Text(_uploading ? 'Reading…' : 'Add a document'),
                      ),
                      const SizedBox(width: 12),
                      FilterChip(
                        key: const Key('document-private'),
                        selected: _private,
                        onSelected: (v) => setState(() => _private = v),
                        avatar: Icon(_private ? Icons.lock : Icons.lock_open, size: 16),
                        label: const Text('Private'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),
            ...docs.when(
              loading: () => [const LinearProgressIndicator(minHeight: 2)],
              error: (e, _) => [Text(e is ApiException ? e.message : 'Could not load documents')],
              data: (list) => list.isEmpty
                  ? [
                      const Padding(
                        padding: EdgeInsets.all(24),
                        child: Text(
                          'No documents yet.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: UltronColors.textSecondary),
                        ),
                      ),
                    ]
                  : [
                      for (final d in list)
                        Padding(
                          key: Key('document-${d.id}'),
                          padding: const EdgeInsets.only(bottom: 10),
                          child: GlassPanel(
                            padding: const EdgeInsets.fromLTRB(16, 8, 6, 8),
                            child: Row(
                              children: [
                                Icon(documentIcon(d.kind), color: Theme.of(context).colorScheme.primary),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(d.name, style: const TextStyle(fontWeight: FontWeight.w600)),
                                      Text(
                                        [
                                          d.sizeLabel,
                                          if (d.pages != null) '${d.pages} pages',
                                          '${d.chunkCount} parts',
                                          if (d.isPrivate) 'private',
                                        ].join(' · '),
                                        style: const TextStyle(fontSize: 11.5, color: UltronColors.textMuted),
                                      ),
                                    ],
                                  ),
                                ),
                                if (d.isPrivate) const Icon(Icons.lock, size: 16, color: UltronColors.local),
                                TextButton(
                                  key: Key('ask-${d.id}'),
                                  onPressed: () => _ask(d),
                                  child: const Text('Ask about it'),
                                ),
                                IconButton(
                                  key: Key('delete-document-${d.id}'),
                                  tooltip: 'Delete',
                                  onPressed: () async {
                                    try {
                                      await ref.read(documentsProvider.notifier).remove(d);
                                    } on ApiException catch (e) {
                                      if (context.mounted) _toast(context, e.message);
                                    }
                                  },
                                  icon: const Icon(Icons.delete_outline, size: 20),
                                ),
                              ],
                            ),
                          ),
                        ),
                    ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Paperclip in the chat box: attach an existing or new document.
class AttachButton extends ConsumerWidget {
  const AttachButton({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) => IconButton(
    key: const Key('attach-button'),
    tooltip: 'Attach a document',
    onPressed: () => showModalBottomSheet<void>(
      context: context,
      backgroundColor: UltronColors.surface,
      builder: (_) => const _AttachSheet(),
    ),
    icon: const Icon(Icons.attach_file),
  );
}

class _AttachSheet extends ConsumerWidget {
  const _AttachSheet();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final docs = ref.watch(documentsProvider).value ?? const <DocumentInfo>[];
    final chat = ref.watch(chatProvider);
    final usable = [
      for (final d in docs)
        if (!d.isPrivate || chat.isPrivate) d,
    ];
    return SafeArea(
      child: ListView(
        key: const Key('attach-sheet'),
        shrinkWrap: true,
        padding: const EdgeInsets.symmetric(vertical: 12),
        children: [
          ListTile(
            key: const Key('attach-upload'),
            leading: const Icon(Icons.upload_file),
            title: const Text('Add a new document'),
            onTap: () async {
              final messenger = ScaffoldMessenger.of(context);
              final navigator = Navigator.of(context);
              try {
                final doc = await ref.read(documentsProvider.notifier).pickAndUpload(private: chat.isPrivate);
                if (doc != null) ref.read(chatProvider.notifier).attach(doc);
                navigator.pop();
              } on ApiException catch (e) {
                messenger.showSnackBar(SnackBar(content: Text(e.message)));
              }
            },
          ),
          if (usable.isNotEmpty) const Divider(),
          for (final d in usable)
            ListTile(
              key: Key('attach-${d.id}'),
              leading: Icon(documentIcon(d.kind)),
              title: Text(d.name),
              trailing: chat.attachments.any((a) => a.id == d.id) ? const Icon(Icons.check) : null,
              onTap: () {
                ref.read(chatProvider.notifier).attach(d);
                Navigator.of(context).pop();
              },
            ),
        ],
      ),
    );
  }
}

/// Attached documents, above the chat box.
class AttachmentsBar extends ConsumerWidget {
  const AttachmentsBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final attachments = ref.watch(chatProvider.select((s) => s.attachments));
    if (attachments.isEmpty) return const SizedBox.shrink();
    return Padding(
      key: const Key('attachments-bar'),
      padding: const EdgeInsets.only(bottom: 8),
      child: Wrap(
        spacing: 8,
        runSpacing: 6,
        children: [
          for (final d in attachments)
            InputChip(
              key: Key('attached-${d.id}'),
              avatar: Icon(documentIcon(d.kind), size: 16),
              label: Text(d.name, overflow: TextOverflow.ellipsis),
              onDeleted: () => ref.read(chatProvider.notifier).detach(d.id),
            ),
        ],
      ),
    );
  }
}
