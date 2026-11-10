import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import 'pinning.dart';

/// What people compare by eye (same format as ULTRON Core shows).
String shortFingerprint(String fp) {
  final f = fp.toUpperCase();
  return '${f.substring(0, 4)}-${f.substring(4, 8)} … ${f.substring(f.length - 8, f.length - 4)}-${f.substring(f.length - 4)}';
}

/// Reads the certificate fingerprint an https server presents (tests
/// replace it).
final fingerprintProbeProvider = Provider<Future<String?> Function(Uri)>((ref) => serverFingerprint);

/// A client that trusts exactly one certificate (tests replace it).
final pinnedClientFactoryProvider = Provider<http.Client Function(String)>(
  (ref) =>
      (fp) => createClient(pinnedFingerprint: fp),
);
