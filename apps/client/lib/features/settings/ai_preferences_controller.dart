import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/models.dart';
import '../../core/auth/session.dart';
import '../../core/providers.dart';
import '../../core/status/system_status.dart';
import '../chat/chat_controller.dart';

/// AI routing preferences stored on the backend (shared by all devices).
final aiPreferencesProvider = AsyncNotifierProvider<AiPreferencesController, AiPreferences?>(
  AiPreferencesController.new,
);

class AiPreferencesController extends AsyncNotifier<AiPreferences?> {
  @override
  Future<AiPreferences?> build() async {
    if (ref.watch(sessionProvider) is! SignedIn) return null;
    final prefs = await ref.watch(apiProvider).aiPreferences();
    ref.read(chatProvider.notifier).applyPrivateDefault(prefs.privateByDefault);
    return prefs;
  }

  /// Saves and returns the server's copy. Throws ApiException on failure
  /// (the previous value stays shown).
  Future<void> save(AiPreferences updated) async {
    final saved = await ref.read(apiProvider).saveAiPreferences(updated);
    state = AsyncData(saved);
    ref.read(chatProvider.notifier).applyPrivateDefault(saved.privateByDefault);
    // Routing mode is reported in AI status; refresh it.
    await ref.read(systemStatusProvider.notifier).refresh();
  }
}
