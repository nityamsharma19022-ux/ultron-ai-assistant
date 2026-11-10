import 'package:flutter/material.dart';

import '../../core/status/system_status.dart';
import '../../core/theme/ultron_colors.dart';
import '../chat/chat_state.dart';

/// What the visualizer is expressing.
enum VisualizerMode {
  idle('Idle'),
  listening('Listening'),
  thinking('Thinking'),
  loadingModel('Loading local model'),
  generating('Generating'),
  speaking('Speaking'),
  offline('Offline');

  const VisualizerMode(this.label);
  final String label;
}

/// How the core moves in each mode.
@immutable
class VisualizerStyle {
  const VisualizerStyle({required this.speed, required this.energy, required this.pulse, required this.glow});

  /// Rotation speed multiplier.
  final double speed;

  /// Height of the reactive bars (0–1).
  final double energy;

  /// How strongly the core breathes (0–1).
  final double pulse;

  /// Brightness of the outer glow (0–1).
  final double glow;

  static VisualizerStyle of(VisualizerMode mode) => switch (mode) {
    VisualizerMode.idle => const VisualizerStyle(speed: 0.35, energy: 0.12, pulse: 0.35, glow: 0.45),
    VisualizerMode.listening => const VisualizerStyle(speed: 0.6, energy: 0.35, pulse: 0.5, glow: 0.7),
    VisualizerMode.thinking => const VisualizerStyle(speed: 1.5, energy: 0.3, pulse: 0.8, glow: 0.65),
    VisualizerMode.loadingModel => const VisualizerStyle(speed: 2.2, energy: 0.2, pulse: 0.6, glow: 0.55),
    VisualizerMode.generating => const VisualizerStyle(speed: 1.0, energy: 0.85, pulse: 0.6, glow: 0.9),
    VisualizerMode.speaking => const VisualizerStyle(speed: 0.8, energy: 0.7, pulse: 0.7, glow: 0.85),
    VisualizerMode.offline => const VisualizerStyle(speed: 0.08, energy: 0.03, pulse: 0.1, glow: 0.15),
  };

  VisualizerStyle lerp(VisualizerStyle to, double t) => VisualizerStyle(
    speed: speed + (to.speed - speed) * t,
    energy: energy + (to.energy - energy) * t,
    pulse: pulse + (to.pulse - pulse) * t,
    glow: glow + (to.glow - glow) * t,
  );
}

/// Picks the mode from what the app is doing. Voice activity wins over the
/// reply phase; an unreachable backend dims the core.
VisualizerMode visualizerModeFor({
  required ReplyPhase phase,
  required BackendLink link,
  bool listening = false,
  bool speaking = false,
}) {
  if (listening) return VisualizerMode.listening;
  switch (phase) {
    case ReplyPhase.routing:
    case ReplyPhase.waiting:
      return VisualizerMode.thinking;
    case ReplyPhase.loadingModel:
      return VisualizerMode.loadingModel;
    case ReplyPhase.generating:
      return VisualizerMode.generating;
    case ReplyPhase.idle:
      break;
  }
  if (speaking) return VisualizerMode.speaking;
  if (link == BackendLink.offline) return VisualizerMode.offline;
  return VisualizerMode.idle;
}

/// Colour of the core: green while local AI answers, blue for cloud AI,
/// grey when offline, otherwise the user's accent.
Color visualizerColor(VisualizerMode mode, Color accent, {String? aiKind}) {
  if (mode == VisualizerMode.offline) return UltronColors.textMuted;
  if (mode == VisualizerMode.generating || mode == VisualizerMode.loadingModel) {
    if (aiKind == 'local') return UltronColors.local;
    if (aiKind == 'cloud') return UltronColors.cloud;
  }
  return accent;
}
