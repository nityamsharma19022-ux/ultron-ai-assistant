/// An error from the ULTRON backend or the network, with a message that is
/// safe to show to the user.
class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode, this.code});

  /// No connection to the backend at all.
  const ApiException.network([String message = 'Cannot reach the ULTRON backend. Is it running?'])
    : this(message, code: 'network');

  final String message;
  final int? statusCode;
  final String? code;

  bool get isNetwork => code == 'network';
  bool get isUnauthorized => statusCode == 401;

  @override
  String toString() => 'ApiException($statusCode, $code): $message';
}
