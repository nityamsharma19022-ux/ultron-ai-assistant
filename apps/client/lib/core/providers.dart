import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import 'api/ultron_api.dart';
import 'auth/token_store.dart';
import 'net/pinning.dart';
import 'settings/app_settings.dart';

/// HTTP client (trusts ULTRON Core's pinned certificate). Replaced in tests
/// with a MockClient.
final httpClientProvider = Provider<http.Client>((ref) {
  final pin = ref.watch(settingsProvider.select((s) => s.tlsFingerprint));
  final client = createClient(pinnedFingerprint: pin);
  ref.onDispose(client.close);
  return client;
});

/// Replaced in tests with a MemoryTokenStore.
final tokenStoreProvider = Provider<TokenStore>((ref) => SecureTokenStore());

/// API client for the backend address chosen in settings.
final apiProvider = Provider<UltronApi>((ref) {
  final url = ref.watch(settingsProvider.select((s) => s.backendUrl));
  return UltronApi(baseUrl: url, tokens: ref.watch(tokenStoreProvider), client: ref.watch(httpClientProvider));
});
