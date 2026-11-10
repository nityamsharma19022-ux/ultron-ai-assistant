import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

String _sha256(X509Certificate cert) => sha256.convert(cert.der).toString();

/// Normal certificate checks, plus: ULTRON Core's own self-signed
/// certificate is accepted when its SHA-256 matches the pinned fingerprint
/// (saved when the device was paired). Nothing else is relaxed.
http.Client createClient({String? pinnedFingerprint}) {
  final pin = pinnedFingerprint?.toLowerCase();
  final inner = HttpClient()..connectionTimeout = const Duration(seconds: 10);
  if (pin != null && pin.isNotEmpty) {
    inner.badCertificateCallback = (cert, host, port) => _sha256(cert) == pin;
  }
  return IOClient(inner);
}

/// The SHA-256 of the certificate an https server presents (null for http
/// or if it can't be reached). Used once, while pairing, so the user can
/// compare it with what their PC shows.
Future<String?> serverFingerprint(Uri url) async {
  if (url.scheme != 'https') return null;
  String? seen;
  final client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 10)
    ..badCertificateCallback = (cert, host, port) {
      seen = _sha256(cert);
      return true; // only for this probe request, which sends nothing secret
    };
  try {
    final request = await client.getUrl(url.replace(path: '/health/live'));
    final response = await request.close();
    seen ??= response.certificate == null ? null : _sha256(response.certificate!);
    await response.drain<void>();
    return seen;
  } on Object {
    return null;
  } finally {
    client.close(force: true);
  }
}
