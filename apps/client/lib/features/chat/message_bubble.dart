import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/api/models.dart';
import '../../core/theme/ultron_colors.dart';
import '../../widgets/ai_source_badge.dart';

class MessageBubble extends StatelessWidget {
  const MessageBubble({super.key, required this.message, this.onRetry});
  final ChatMessage message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    final user = message.isUser;
    final streaming = message.status == MessageStatus.streaming;
    final maxWidth = MediaQuery.sizeOf(context).width * (MediaQuery.sizeOf(context).width > 900 ? 0.6 : 0.82);

    final text = message.content.isEmpty && streaming
        ? const _TypingDots()
        : SelectableText.rich(
            TextSpan(
              text: message.content,
              children: [
                if (streaming)
                  WidgetSpan(
                    alignment: PlaceholderAlignment.middle,
                    child: _Cursor(color: accent),
                  ),
              ],
            ),
            style: const TextStyle(fontSize: 15, height: 1.5, color: UltronColors.textPrimary),
          );

    final bubble = Container(
      constraints: BoxConstraints(maxWidth: maxWidth),
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      decoration: BoxDecoration(
        color: user ? accent.withValues(alpha: 0.14) : UltronColors.panel,
        borderRadius: BorderRadius.only(
          topLeft: const Radius.circular(16),
          topRight: const Radius.circular(16),
          bottomLeft: Radius.circular(user ? 16 : 4),
          bottomRight: Radius.circular(user ? 4 : 16),
        ),
        border: Border.all(color: (user ? accent : UltronColors.panelBorder).withValues(alpha: user ? 0.35 : 1)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [text, if (!user) ..._footer(context)],
      ),
    );

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: user ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [Flexible(child: bubble)],
      ),
    );
  }

  List<Widget> _footer(BuildContext context) {
    final widgets = <Widget>[];
    final problem = switch (message.status) {
      MessageStatus.cancelled => 'Stopped',
      MessageStatus.incomplete => message.errorMessage ?? 'The reply was interrupted.',
      MessageStatus.failed => message.errorMessage ?? 'No reply could be produced.',
      _ => null,
    };
    if (message.providerKind != null || problem != null || message.status == MessageStatus.complete) {
      widgets.add(const SizedBox(height: 10));
    }
    if (problem != null) {
      final failed = message.status != MessageStatus.cancelled;
      widgets.add(
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              failed ? Icons.error_outline : Icons.stop_circle_outlined,
              size: 15,
              color: failed ? UltronColors.danger : UltronColors.textSecondary,
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                problem,
                key: Key('error-${message.id}'),
                style: TextStyle(fontSize: 12.5, color: failed ? UltronColors.danger : UltronColors.textSecondary),
              ),
            ),
            if (onRetry != null && failed) TextButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      );
      widgets.add(const SizedBox(height: 6));
    }
    widgets.add(
      Row(
        children: [
          if (message.providerKind != null)
            Expanded(
              child: AiSourceBadge(
                kind: message.providerKind!,
                provider: message.provider,
                model: message.model,
                fallback: message.fallbackUsed,
              ),
            )
          else
            const Spacer(),
          if (message.content.isNotEmpty && message.status != MessageStatus.streaming)
            IconButton(
              tooltip: 'Copy',
              visualDensity: VisualDensity.compact,
              iconSize: 16,
              color: UltronColors.textMuted,
              icon: const Icon(Icons.copy_rounded),
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: message.content));
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Copied')));
                }
              },
            ),
        ],
      ),
    );
    return widgets;
  }
}

class _Cursor extends StatefulWidget {
  const _Cursor({required this.color});
  final Color color;

  @override
  State<_Cursor> createState() => _CursorState();
}

class _CursorState extends State<_Cursor> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 700))
    ..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
    opacity: _c,
    child: Container(
      margin: const EdgeInsets.only(left: 2),
      width: 8,
      height: 16,
      decoration: BoxDecoration(color: widget.color, borderRadius: BorderRadius.circular(2)),
    ),
  );
}

class _TypingDots extends StatefulWidget {
  const _TypingDots();

  @override
  State<_TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<_TypingDots> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1200))
    ..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return SizedBox(
      key: const Key('typing-dots'),
      height: 20,
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) => Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (var i = 0; i < 3; i++)
              Container(
                margin: const EdgeInsets.symmetric(horizontal: 3),
                width: 7,
                height: 7,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: accent.withValues(alpha: 0.25 + 0.75 * _wave(_c.value, i)),
                ),
              ),
          ],
        ),
      ),
    );
  }

  static double _wave(double t, int i) {
    final x = (t - i * 0.18) % 1.0;
    return x < 0.5 ? x * 2 : (1 - x) * 2;
  }
}
