import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/task_models.dart';
import '../../core/auth/session.dart';
import '../../core/notices.dart';
import '../../core/platform/native.dart';
import '../../core/providers.dart';

const phoneTools = ['phone.status', 'phone.apps.open', 'phone.notify', 'phone.alarm.set', 'phone.timer.set'];

class PhoneAgentState {
  const PhoneAgentState({this.active = false, this.lastStep, this.error});
  final bool active;
  final String? lastStep;
  final String? error;
}

/// Runs ULTRON's phone steps while the app is open on Android: says hello
/// with the phone tools, long-polls for steps and runs them through the
/// native channel. Android limits background work, so the phone only takes
/// steps while ULTRON is open (or opened by the assistant).
final phoneAgentProvider = NotifierProvider<PhoneAgent, PhoneAgentState>(PhoneAgent.new);

class PhoneAgent extends Notifier<PhoneAgentState> {
  int _generation = 0;
  Duration idleDelay = const Duration(seconds: 1);

  /// How often the phone reports battery and network to the Command Center.
  Duration metricsEvery = const Duration(seconds: 60);
  DateTime? _lastMetrics;
  Timer? _sleepTimer;
  Completer<void>? _sleeping;

  /// A pause that [stop] can cut short (no timers left behind).
  Future<void> _sleep(Duration d) {
    final done = _sleeping = Completer<void>();
    _sleepTimer = Timer(d, () {
      if (!done.isCompleted) done.complete();
    });
    return done.future;
  }

  void _wakeUp() {
    _sleepTimer?.cancel();
    final s = _sleeping;
    if (s != null && !s.isCompleted) s.complete();
  }

  @override
  PhoneAgentState build() {
    // Start/stop after build returns (the state doesn't exist during build).
    ref.listen(
      sessionProvider,
      (_, next) => scheduleMicrotask(() => next is SignedIn ? start() : stop()),
      fireImmediately: true,
    );
    ref.onDispose(() {
      _generation++;
      _wakeUp();
    });
    return const PhoneAgentState();
  }

  PhonePlatform get _phone => ref.read(phonePlatformProvider);

  void start() {
    if (!_phone.supported || state.active) return;
    final gen = ++_generation;
    state = const PhoneAgentState(active: true);
    unawaited(_loop(gen));
  }

  void stop() {
    _generation++;
    _wakeUp();
    if (state.active) state = const PhoneAgentState();
  }

  Future<void> _loop(int gen) async {
    var backoff = const Duration(seconds: 2);
    var greeted = false;
    while (gen == _generation) {
      try {
        final api = ref.read(apiProvider);
        if (!greeted) {
          final apps = await _phone.apps();
          await api.agentHello(phoneTools, capabilities: {'apps': apps.take(100).toList()}, version: 'app');
          greeted = true;
        }
        await _maybePushMetrics();
        final work = await api.nextStep();
        if (gen != _generation) return;
        backoff = const Duration(seconds: 2);
        if (work == null) {
          await _sleep(idleDelay);
          continue;
        }
        await _execute(work);
      } on ApiException catch (e) {
        if (gen != _generation) return;
        if (e.isUnauthorized) return stop();
        state = PhoneAgentState(active: true, error: e.message);
        greeted = false;
        await _sleep(backoff);
        backoff = backoff * 2 > const Duration(seconds: 60) ? const Duration(seconds: 60) : backoff * 2;
      }
    }
  }

  Future<void> _maybePushMetrics() async {
    final now = DateTime.now();
    if (_lastMetrics != null && now.difference(_lastMetrics!) < metricsEvery) return;
    _lastMetrics = now;
    try {
      final s = await _phone.call('status');
      final values = <String, dynamic>{
        if (s['battery_percent'] is num) 'battery_percent': s['battery_percent'],
        if (s['charging'] is bool) 'charging': s['charging'],
        if (s['network'] is String) 'network': s['network'],
      };
      if (values.isNotEmpty) await ref.read(apiProvider).pushMetrics(values);
    } on Object {
      // Metrics are optional; steps keep running.
    }
  }

  Future<void> _execute(StepWork work) async {
    final api = ref.read(apiProvider);
    Map<String, dynamic> result;
    final a = work.args;
    try {
      result = switch (work.tool) {
        'phone.status' => await _phone.call('status'),
        'phone.apps.open' => await _phone.call('openApp', {'app': a['app']}),
        'phone.notify' => await _phone.call('notify', {
          'id': work.id.hashCode & 0x7fffffff,
          'title': a['title'] ?? 'ULTRON',
          'text': a['text'] ?? '',
        }),
        'phone.alarm.set' => await _phone.call('setAlarm', {
          'hour': a['hour'],
          'minute': a['minute'] ?? 0,
          'label': a['label'] ?? 'ULTRON',
        }),
        'phone.timer.set' => await _phone.call('setTimer', {'seconds': a['seconds'], 'label': a['label'] ?? 'ULTRON'}),
        _ => {'ok': false, 'error': "This phone doesn't offer ${work.tool}"},
      };
    } on Object catch (e) {
      result = {'ok': false, 'error': 'Phone error: $e'};
    }
    final ok = result.remove('ok') != false;
    final error = result.remove('error') as String?;
    state = PhoneAgentState(active: true, lastStep: work.title);
    await api.stepResult(work.id, ok: ok, result: result, error: error);
  }
}

/// Shows reminders when they're due: a phone notification on Android and a
/// message in the app everywhere.
final reminderWatcherProvider = NotifierProvider<ReminderWatcher, void>(ReminderWatcher.new);

class ReminderWatcher extends Notifier<void> {
  Timer? _timer;

  @override
  void build() {
    ref.listen(sessionProvider, (_, next) {
      _timer?.cancel();
      if (next is SignedIn) _timer = Timer.periodic(const Duration(seconds: 30), (_) => check());
    }, fireImmediately: true);
    ref.onDispose(() => _timer?.cancel());
  }

  Future<void> check() async {
    final api = ref.read(apiProvider);
    try {
      for (final r in await api.reminders(due: true)) {
        final phone = ref.read(phonePlatformProvider);
        if (phone.supported) {
          await phone.call('notify', {'id': r.id.hashCode & 0x7fffffff, 'title': 'Reminder', 'text': r.text});
        }
        ref.read(noticesProvider.notifier).show('⏰ Reminder: ${r.text}');
        await api.markReminder(r.id, delivered: true);
      }
    } on ApiException {
      // Try again on the next round.
    }
  }
}
