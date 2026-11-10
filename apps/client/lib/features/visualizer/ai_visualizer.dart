import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../../core/settings/app_settings.dart';
import 'core_painter.dart';
import 'visualizer_mode.dart';

/// The animated ULTRON core. Changes smoothly between modes; honours the
/// motion setting (Off = a still image, no animation at all).
class AiVisualizer extends StatefulWidget {
  const AiVisualizer({
    super.key,
    required this.mode,
    required this.color,
    this.size = 240,
    this.level = 0,
    this.motion = MotionLevel.full,
  });

  final VisualizerMode mode;
  final Color color;
  final double size;

  /// Live microphone level 0–1.
  final double level;
  final MotionLevel motion;

  @override
  State<AiVisualizer> createState() => AiVisualizerState();
}

class AiVisualizerState extends State<AiVisualizer> with SingleTickerProviderStateMixin {
  late final Ticker _ticker = createTicker(_tick);
  late VisualizerStyle _style = VisualizerStyle.of(widget.mode);
  late Color _color = widget.color;
  double _phase = 0.6;
  double _level = 0;
  Duration _last = Duration.zero;

  @visibleForTesting
  bool get animating => _ticker.isActive;

  @visibleForTesting
  VisualizerStyle get currentStyle => _style;

  @override
  void initState() {
    super.initState();
    _syncTicker();
  }

  @override
  void didUpdateWidget(AiVisualizer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.motion != widget.motion) _syncTicker();
    if (widget.motion == MotionLevel.off) {
      // No animation: jump straight to the new look.
      _style = VisualizerStyle.of(widget.mode);
      _color = widget.color;
      _level = widget.level;
    }
  }

  void _syncTicker() {
    final shouldRun = widget.motion != MotionLevel.off;
    if (shouldRun && !_ticker.isActive) {
      _last = Duration.zero;
      _ticker.start();
    } else if (!shouldRun && _ticker.isActive) {
      _ticker.stop();
    }
  }

  void _tick(Duration elapsed) {
    final dt = ((elapsed - _last).inMicroseconds / 1e6).clamp(0.0, 0.1);
    _last = elapsed;
    final target = VisualizerStyle.of(widget.mode);
    final ease = (dt * 4).clamp(0.0, 1.0);
    final slow = widget.motion == MotionLevel.reduced ? 0.35 : 1.0;
    setState(() {
      _style = _style.lerp(target, ease);
      _color = Color.lerp(_color, widget.color, ease)!;
      _level += (widget.level - _level) * (dt * 12).clamp(0.0, 1.0);
      _phase += dt * _style.speed * slow * 2.2;
    });
  }

  @override
  void dispose() {
    _ticker.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Semantics(
    label: 'ULTRON status: ${widget.mode.label}',
    image: true,
    child: RepaintBoundary(
      child: SizedBox.square(
        dimension: widget.size,
        child: CustomPaint(
          painter: CorePainter(
            phase: _phase,
            style: _style,
            color: _color,
            level: _level,
            detail: widget.motion == MotionLevel.full ? 1 : 0,
            sweep: widget.mode == VisualizerMode.loadingModel,
          ),
        ),
      ),
    ),
  );
}
