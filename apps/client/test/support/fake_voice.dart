import 'dart:async';

import 'package:ultron_app/features/voice/speech_engines.dart';

/// Scriptable speech recogniser.
class FakeSpeechInput implements SpeechInput {
  FakeSpeechInput({this.recognisesOnDevice = true, this.available = true});

  @override
  bool recognisesOnDevice;
  bool available;
  int initCalls = 0, listenCalls = 0, stopCalls = 0, cancelCalls = 0;
  String? lastLocale;
  String _heard = '';
  void Function(String text, bool isFinal)? _onResult;
  void Function(double level)? _onLevel;
  void Function()? _onDone;
  void Function(String message)? _onError;
  void Function()? _onProcessing;

  /// Like the Windows plugin bug: stop() delivers nothing at all.
  bool silentStop = false;

  @override
  Future<bool> initialize() async {
    initCalls++;
    return available;
  }

  @override
  Future<void> listen({
    String? localeId,
    required void Function(String text, bool isFinal) onResult,
    required void Function(double level) onLevel,
    required void Function() onDone,
    required void Function(String message) onError,
    void Function()? onProcessing,
  }) async {
    listenCalls++;
    _onProcessing = onProcessing;
    lastLocale = localeId;
    _heard = '';
    _onResult = onResult;
    _onLevel = onLevel;
    _onDone = onDone;
    _onError = onError;
  }

  /// Simulates the user speaking (a partial result).
  void hear(String text) {
    _heard = text;
    _onResult?.call(text, false);
  }

  void level(double value) => _onLevel?.call(value);
  void processing() => _onProcessing?.call();
  void fail(String message) => _onError?.call(message);

  /// Like the real plugin: stopping delivers the final result, then "done".
  @override
  Future<void> stop() async {
    stopCalls++;
    if (silentStop) return;
    _onResult?.call(_heard, true);
    _onDone?.call();
  }

  @override
  Future<void> cancel() async => cancelCalls++;
}

/// Records what would be spoken.
class FakeSpeechOutput implements SpeechOutput {
  final spoken = <({String text, bool localOnly, double rate})>[];
  SpeakOutcome outcome = SpeakOutcome.spoken;

  /// When true, speaking lasts until [stop] or [finish].
  bool holdSpeech = false;
  int stopCalls = 0;
  Completer<void>? _current;

  @override
  Future<SpeakOutcome> speak(String text, {required double rate, String? locale, required bool localOnly}) async {
    if (outcome != SpeakOutcome.spoken) return outcome;
    spoken.add((text: text, localOnly: localOnly, rate: rate));
    if (holdSpeech) await (_current = Completer<void>()).future;
    return SpeakOutcome.spoken;
  }

  void finish() {
    if (_current?.isCompleted == false) _current!.complete();
  }

  @override
  Future<void> stop() async {
    stopCalls++;
    finish();
  }
}
