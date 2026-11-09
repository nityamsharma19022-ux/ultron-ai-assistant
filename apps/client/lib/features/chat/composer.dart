import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/theme/ultron_colors.dart';

/// Message input. Enter sends on desktop (Shift+Enter for a new line); the
/// send button becomes a stop button while a reply is being generated.
class Composer extends StatefulWidget {
  const Composer({
    super.key,
    required this.busy,
    required this.onSend,
    required this.onStop,
    this.leading,
    this.hint = 'Message ULTRON…',
    this.controller,
  });

  final bool busy;
  final ValueChanged<String> onSend;
  final VoidCallback onStop;

  /// Extra controls on the left (voice button).
  final Widget? leading;
  final String hint;
  final TextEditingController? controller;

  @override
  State<Composer> createState() => _ComposerState();
}

class _ComposerState extends State<Composer> {
  late final TextEditingController _text = widget.controller ?? TextEditingController();
  final _focus = FocusNode();

  @override
  void dispose() {
    if (widget.controller == null) _text.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _submit() {
    if (widget.busy) return;
    final value = _text.text.trim();
    if (value.isEmpty) return;
    widget.onSend(value);
    _text.clear();
    _focus.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 6, 6, 6),
      decoration: BoxDecoration(
        color: UltronColors.surface.withValues(alpha: 0.85),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: accent.withValues(alpha: 0.28)),
        boxShadow: [BoxShadow(color: accent.withValues(alpha: 0.08), blurRadius: 24)],
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          ?widget.leading,
          Expanded(
            child: CallbackShortcuts(
              bindings: {
                const SingleActivator(LogicalKeyboardKey.enter): _submit,
                const SingleActivator(LogicalKeyboardKey.numpadEnter): _submit,
              },
              child: TextField(
                key: const Key('composer-input'),
                controller: _text,
                focusNode: _focus,
                minLines: 1,
                maxLines: 6,
                textInputAction: TextInputAction.newline,
                keyboardType: TextInputType.multiline,
                style: const TextStyle(fontSize: 15),
                decoration: InputDecoration(
                  hintText: widget.hint,
                  filled: false,
                  border: InputBorder.none,
                  enabledBorder: InputBorder.none,
                  focusedBorder: InputBorder.none,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
                ),
              ),
            ),
          ),
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 200),
            child: widget.busy
                ? IconButton.filledTonal(
                    key: const Key('stop-button'),
                    tooltip: 'Stop',
                    onPressed: widget.onStop,
                    icon: const Icon(Icons.stop_rounded),
                  )
                : IconButton.filled(
                    key: const Key('send-button'),
                    tooltip: 'Send',
                    onPressed: _submit,
                    icon: const Icon(Icons.arrow_upward_rounded),
                  ),
          ),
        ],
      ),
    );
  }
}
