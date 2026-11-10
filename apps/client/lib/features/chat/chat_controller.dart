import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/models.dart';
import '../../core/api/ultron_api.dart';
import '../../core/auth/session.dart';
import '../../core/providers.dart';
import 'chat_state.dart';

/// Conversation list (newest first).
final conversationsProvider = AsyncNotifierProvider<ConversationsController, List<Conversation>>(
  ConversationsController.new,
);

class ConversationsController extends AsyncNotifier<List<Conversation>> {
  @override
  Future<List<Conversation>> build() async {
    if (ref.watch(sessionProvider) is! SignedIn) return const [];
    return ref.watch(apiProvider).conversations();
  }

  Future<void> reload() async {
    final api = ref.read(apiProvider);
    state = await AsyncValue.guard(api.conversations);
  }

  Future<void> delete(String id) async {
    await ref.read(apiProvider).deleteConversation(id);
    state = AsyncData([...?state.value?.where((c) => c.id != id)]);
  }

  void upsert(Conversation c) {
    final others = [...?state.value?.where((x) => x.id != c.id)];
    state = AsyncData([c, ...others]);
  }
}

final chatProvider = NotifierProvider<ChatController, ChatState>(ChatController.new);

/// The open conversation and the reply being streamed into it.
class ChatController extends Notifier<ChatState> {
  StreamSubscription<ChatStreamEvent>? _sub;
  Completer<void>? _abort;
  int _tempIds = 0;
  bool _privateDefault = false;

  UltronApi get _api => ref.read(apiProvider);

  @override
  ChatState build() {
    ref.watch(apiProvider);
    ref.onDispose(_stopStreaming);
    return const ChatState();
  }

  void _stopStreaming() {
    if (_abort != null && !_abort!.isCompleted) _abort!.complete();
    _sub?.cancel();
    _sub = null;
  }

  /// Start a fresh conversation (created on the first message).
  void newConversation({bool? private}) {
    _stopStreaming();
    state = ChatState(newChatPrivate: private ?? _privateDefault);
  }

  /// Applies the "private by default" preference to a fresh, empty chat.
  void applyPrivateDefault(bool value) {
    _privateDefault = value;
    if (state.conversation == null && state.messages.isEmpty) state = state.copyWith(newChatPrivate: value);
  }

  void setNewChatPrivate(bool value) {
    if (state.conversation == null) state = state.copyWith(newChatPrivate: value);
  }

  Future<void> open(String conversationId) async {
    _stopStreaming();
    state = ChatState(loading: true, newChatPrivate: state.newChatPrivate);
    try {
      final (conversation, messages) = await _api.conversation(conversationId);
      state = state.copyWith(conversation: conversation, messages: messages, loading: false);
    } on ApiException catch (e) {
      state = state.copyWith(loading: false, loadError: e.message);
    }
  }

  /// Turns the open conversation private (cannot be undone).
  Future<void> makePrivate() async {
    final c = state.conversation;
    if (c == null || c.isPrivate) return;
    final updated = await _api.updateConversation(c.id, makePrivate: true);
    state = state.copyWith(conversation: updated);
    ref.read(conversationsProvider.notifier).upsert(updated);
  }

  Future<void> send(String text) async {
    final content = text.trim();
    if (content.isEmpty || state.busy) return;

    final userTemp = ChatMessage(
      id: 'local-${_tempIds++}',
      role: 'user',
      content: content,
      status: MessageStatus.complete,
      timestamp: DateTime.now(),
    );
    var assistantId = 'local-${_tempIds++}';
    final placeholder = ChatMessage(
      id: assistantId,
      role: 'assistant',
      content: '',
      status: MessageStatus.streaming,
      timestamp: DateTime.now(),
    );
    state = state.copyWith(
      messages: [...state.messages, userTemp, placeholder],
      phase: ReplyPhase.routing,
      clearLoadError: true,
    );

    void updateAssistant(ChatMessage Function(ChatMessage m) change) {
      state = state.copyWith(messages: [for (final m in state.messages) m.id == assistantId ? change(m) : m]);
    }

    void fail(String code, String message) {
      updateAssistant(
        (m) => m.copyWith(
          status: m.content.isEmpty ? MessageStatus.failed : MessageStatus.incomplete,
          errorCode: code,
          errorMessage: friendlyError(code, message),
        ),
      );
      state = state.copyWith(phase: ReplyPhase.idle);
    }

    // Create the conversation on the first message.
    var conversation = state.conversation;
    if (conversation == null) {
      try {
        conversation = await _api.createConversation(isPrivate: state.newChatPrivate);
        state = state.copyWith(conversation: conversation);
        ref.read(conversationsProvider.notifier).upsert(conversation);
      } on ApiException catch (e) {
        fail(e.code ?? 'error', e.message);
        return;
      }
    }

    final abort = _abort = Completer<void>();
    final done = Completer<void>();
    _sub = _api
        .sendMessage(conversation.id, content, abort: abort.future)
        .listen(
          (event) {
            switch (event) {
              case StreamCreated(:final userMessage, :final assistantMessageId):
                // Swap the temporary ids for the server's real ones.
                final old = assistantId;
                assistantId = assistantMessageId;
                state = state.copyWith(
                  messages: [
                    for (final m in state.messages)
                      if (m.id == userTemp.id)
                        userMessage
                      else if (m.id == old)
                        ChatMessage(
                          id: assistantMessageId,
                          role: 'assistant',
                          content: m.content,
                          status: MessageStatus.streaming,
                          timestamp: m.timestamp,
                        )
                      else
                        m,
                  ],
                );
              case StreamStatus(:final phase, :final provider, :final kind, :final model):
                state = state.copyWith(
                  phase: ReplyPhase.fromServer(phase),
                  phaseProvider: provider,
                  phaseKind: kind,
                  phaseModel: model,
                );
              case StreamProviderSelected(:final provider, :final kind, :final model, :final fallbackUsed):
                updateAssistant(
                  (m) => m.copyWith(provider: provider, providerKind: kind, model: model, fallbackUsed: fallbackUsed),
                );
              case StreamDelta(:final text):
                updateAssistant((m) => m.copyWith(content: m.content + text));
              case StreamCompleted(:final assistantMessage):
                updateAssistant((_) => assistantMessage);
                state = state.copyWith(phase: ReplyPhase.idle);
              case StreamCancelled(:final assistantMessage):
                updateAssistant((_) => assistantMessage);
                state = state.copyWith(phase: ReplyPhase.idle);
              case StreamFailed(:final code, :final message, :final assistantMessage):
                if (assistantMessage != null) {
                  updateAssistant((_) => assistantMessage);
                  assistantId = assistantMessage.id;
                }
                fail(code, message);
            }
          },
          onError: (Object e) {
            if (e is ApiException) {
              fail(e.code ?? 'error', e.message);
            } else {
              fail('error', 'Something went wrong.');
            }
            if (!done.isCompleted) done.complete();
          },
          onDone: () {
            if (state.busy) fail('stream_stalled', 'The connection was lost while replying.');
            if (!done.isCompleted) done.complete();
          },
          cancelOnError: true,
        );
    await done.future;
    _sub = null;
    // The backend names a conversation after its first message: pick up the
    // new title (and ordering) from the refreshed list.
    await ref.read(conversationsProvider.notifier).reload();
    final fresh = ref.read(conversationsProvider).value?.where((c) => c.id == conversation!.id).firstOrNull;
    if (fresh != null && state.conversation?.id == fresh.id) state = state.copyWith(conversation: fresh);
  }

  /// Stops the reply. The server keeps what was written so far.
  Future<void> cancel() async {
    final c = state.conversation;
    if (!state.busy) return;
    if (c != null) {
      try {
        await _api.cancelReply(c.id);
        return; // the stream reports message.cancelled
      } on ApiException {
        // Nothing running on the server (or offline): stop locally.
      }
    }
    _stopStreaming();
    state = state.copyWith(
      phase: ReplyPhase.idle,
      messages: [
        for (final m in state.messages)
          m.status == MessageStatus.streaming ? m.copyWith(status: MessageStatus.cancelled) : m,
      ],
    );
  }

  /// Sends the user message before [failedReplyId] again.
  Future<void> retry(String failedReplyId) async {
    final i = state.messages.indexWhere((m) => m.id == failedReplyId);
    if (i <= 0) return;
    final prompt = state.messages[i - 1];
    if (!prompt.isUser) return;
    state = state.copyWith(messages: [...state.messages]..removeRange(i - 1, i + 1));
    await send(prompt.content);
  }
}
