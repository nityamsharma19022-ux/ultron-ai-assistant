import 'package:http/http.dart' as http;

/// Web: the browser decides which certificates to trust.
http.Client createClient({String? pinnedFingerprint}) => http.Client();

/// Not available on the web.
Future<String?> serverFingerprint(Uri url) async => null;
