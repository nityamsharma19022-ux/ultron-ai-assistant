import 'package:flutter/foundation.dart';

import '../../core/api/task_models.dart';
import '../../core/api/models.dart';

/// What ULTRON is doing for the current reply (drives loading UI and the
/// visualizer).
enum ReplyPhase {
  idle,
  routing,
  waiting,
  loadingModel,
  generating;

  bool get busy => this != idle;

  static ReplyPhase fromServer(String phase) => switch (phase) {
    'routing' => ReplyPhase.routing,
    'loading_model' => ReplyPhase.loadingModel,
    'generating' => ReplyPhase.generating,
    _ => ReplyPhase.waiting,
  };
}

@immutable
class ChatState {
  const ChatState({
    this.conversation,
    this.messages = const [],
    this.loading = false,
    this.loadError,
    this.phase = ReplyPhase.idle,
    this.phaseProvider,
    this.phaseKind,
    this.phaseModel,
    this.newChatPrivate = false,
    this.attachments = const [],
  });

  /// Null for a new, not yet started conversation.
  final Conversation? conversation;
  final List<ChatMessage> messages;
  final bool loading;
  final String? loadError;
  final ReplyPhase phase;
  final String? phaseProvider;
  final String? phaseKind;
  final String? phaseModel;

  /// Privacy chosen for a new conversation before its first message.
  final bool newChatPrivate;

  /// Documents the AI answers from (kept for follow-up questions).
  final List<DocumentInfo> attachments;

  bool get isPrivate => conversation?.isPrivate ?? newChatPrivate;
  bool get busy => phase.busy;

  ChatState copyWith({
    Conversation? conversation,
    bool clearConversation = false,
    List<ChatMessage>? messages,
    bool? loading,
    String? loadError,
    bool clearLoadError = false,
    ReplyPhase? phase,
    String? phaseProvider,
    String? phaseKind,
    String? phaseModel,
    bool? newChatPrivate,
    List<DocumentInfo>? attachments,
  }) => ChatState(
    conversation: clearConversation ? null : (conversation ?? this.conversation),
    messages: messages ?? this.messages,
    loading: loading ?? this.loading,
    loadError: clearLoadError ? null : (loadError ?? this.loadError),
    phase: phase ?? this.phase,
    phaseProvider: phase == ReplyPhase.idle ? null : (phaseProvider ?? this.phaseProvider),
    phaseKind: phase == ReplyPhase.idle ? null : (phaseKind ?? this.phaseKind),
    phaseModel: phase == ReplyPhase.idle ? null : (phaseModel ?? this.phaseModel),
    newChatPrivate: newChatPrivate ?? this.newChatPrivate,
    attachments: attachments ?? this.attachments,
  );
}

/// Human-readable explanations for the backend's error codes.
String friendlyError(String code, String fallback) => switch (code) {
  'no_ai_available' =>
    'No AI is available right now: cloud providers are not set up or unavailable, '
        'and local AI is not running.',
  'offline_no_local_ai' => 'Cloud AI can\'t be reached and no local model is available.',
  'private_requires_local_ai' =>
    'This conversation is private, so it can only use local AI, '
        'which isn\'t available right now.',
  'local_ai_unavailable' => 'Local AI is not available. Check that Ollama is running.',
  'cloud_ai_unavailable' => 'No cloud AI provider is available right now.',
  'timeout' => 'The reply took too long and was stopped.',
  'refused' => 'The AI declined to answer this request.',
  'rate_limited' => 'Too many messages. Wait a minute and try again.',
  'stream_stalled' => 'The connection was lost while replying.',
  _ => fallback,
};
