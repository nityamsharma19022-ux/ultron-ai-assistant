import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/models.dart';
import '../../core/auth/session.dart';
import '../../core/providers.dart';

/// Devices signed in to this account.
final devicesProvider = AsyncNotifierProvider<DevicesController, List<DeviceInfo>>(DevicesController.new);

class DevicesController extends AsyncNotifier<List<DeviceInfo>> {
  @override
  Future<List<DeviceInfo>> build() async {
    if (ref.watch(sessionProvider) is! SignedIn) return const [];
    return ref.watch(apiProvider).devices();
  }

  Future<void> revoke(String id) async {
    await ref.read(apiProvider).revokeDevice(id);
    state = await AsyncValue.guard(ref.read(apiProvider).devices);
  }
}

/// Local model warm-up: idle, running, done or failed.
sealed class WarmupState {
  const WarmupState();
}

class WarmupIdle extends WarmupState {
  const WarmupIdle();
}

class WarmupRunning extends WarmupState {
  const WarmupRunning();
}

class WarmupDone extends WarmupState {
  const WarmupDone(this.result);
  final WarmupResult result;
}

class WarmupFailed extends WarmupState {
  const WarmupFailed(this.message);
  final String message;
}

final warmupProvider = NotifierProvider<WarmupController, WarmupState>(WarmupController.new);

class WarmupController extends Notifier<WarmupState> {
  @override
  WarmupState build() => const WarmupIdle();

  Future<void> run() async {
    if (state is WarmupRunning) return;
    state = const WarmupRunning();
    try {
      state = WarmupDone(await ref.read(apiProvider).warmupLocalModel());
    } on ApiException catch (e) {
      state = WarmupFailed(e.message);
    }
  }
}
