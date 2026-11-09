import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_exception.dart';
import '../api/models.dart';
import '../providers.dart';

sealed class SessionState {
  const SessionState();
}

/// Checking saved tokens at start-up.
class SessionChecking extends SessionState {
  const SessionChecking();
}

class SignedOut extends SessionState {
  const SignedOut([this.message]);
  final String? message;
}

class SignedIn extends SessionState {
  const SignedIn(this.me);
  final Me me;
}

/// Saved tokens exist but the backend can't be reached right now.
class BackendUnreachable extends SessionState {
  const BackendUnreachable(this.message);
  final String message;
}

final sessionProvider = NotifierProvider<SessionController, SessionState>(SessionController.new);

String platformName() => switch (defaultTargetPlatform) {
  TargetPlatform.windows => 'windows',
  TargetPlatform.android => 'android',
  _ => 'other',
};

String defaultDeviceName() => switch (defaultTargetPlatform) {
  TargetPlatform.windows => 'Windows PC',
  TargetPlatform.android => 'Android phone',
  _ => kIsWeb ? 'Browser preview' : 'Device',
};

class SessionController extends Notifier<SessionState> {
  @override
  SessionState build() {
    // Re-check whenever the backend address changes.
    ref.watch(apiProvider);
    Future.microtask(restore);
    return const SessionChecking();
  }

  Future<void> restore() async {
    final api = ref.read(apiProvider);
    if (await api.tokens.read() == null) {
      state = const SignedOut();
      return;
    }
    try {
      state = SignedIn(await api.me());
    } on ApiException catch (e) {
      state = e.isNetwork ? BackendUnreachable(e.message) : SignedOut(e.isUnauthorized ? e.message : null);
    }
  }

  /// Throws [ApiException] with a user-facing message on failure.
  Future<void> signIn({required String email, required String password, String? deviceName}) async {
    final api = ref.read(apiProvider);
    await api.login(
      email: email,
      password: password,
      deviceName: (deviceName?.trim().isNotEmpty ?? false) ? deviceName!.trim() : defaultDeviceName(),
      platform: platformName(),
    );
    state = SignedIn(await api.me());
  }

  Future<void> signOut() async {
    await ref.read(apiProvider).logout();
    state = const SignedOut();
  }

  /// Called when the API reports that the session has ended.
  void sessionExpired() => state = const SignedOut('Your session has ended. Please sign in again.');
}
