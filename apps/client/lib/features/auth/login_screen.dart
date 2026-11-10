import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/ultron_api.dart';
import '../../core/auth/session.dart';
import '../../core/auth/token_store.dart';
import '../../core/providers.dart';
import '../../core/settings/app_settings.dart';
import '../../core/theme/ultron_colors.dart';
import '../../widgets/glass_panel.dart';
import '../../widgets/ultron_background.dart';
import '../../core/net/fingerprint.dart';
import '../../core/api/task_models.dart';
import '../../widgets/ultron_logo.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key, this.message});
  final String? message;

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _url;
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _device = TextEditingController(text: defaultDeviceName());
  final _code = TextEditingController();
  bool _busy = false;
  bool _showPassword = false;
  bool _pairMode = false;
  String? _error;
  String? _probe;
  bool _probeOk = false;

  @override
  void initState() {
    super.initState();
    _url = TextEditingController(text: ref.read(settingsProvider).backendUrl);
    _error = widget.message;
  }

  @override
  void dispose() {
    for (final c in [_url, _email, _password, _device, _code]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _testConnection() async {
    final problem = validateBackendUrl(_url.text);
    if (problem != null) {
      setState(() => _probe = problem);
      return;
    }
    setState(() {
      _probe = 'Checking…';
      _probeOk = false;
    });
    final api = UltronApi(
      baseUrl: normalizeBackendUrl(_url.text),
      tokens: MemoryTokenStore(),
      client: ref.read(httpClientProvider),
    );
    try {
      final live = await api.healthLive();
      setState(() {
        _probeOk = true;
        _probe = 'Connected to ${live.nodeId} (${live.deployment}, v${live.version})';
      });
    } on ApiException catch (e) {
      setState(() => _probe = e.message);
    }
  }

  /// Pairing: sign in with a code from a signed-in device. Over HTTPS, the
  /// user first checks that the certificate fingerprint matches their PC.
  Future<void> _pair() async {
    if (!(_form.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final url = normalizeBackendUrl(_url.text);
      final settings = ref.read(settingsProvider.notifier);
      if (url.startsWith('https://')) {
        final seen = await ref.read(fingerprintProbeProvider)(Uri.parse(url));
        if (seen == null) throw const ApiException.network("Couldn't reach ULTRON Core over HTTPS.");
        if (seen != ref.read(settingsProvider).tlsFingerprint) {
          final probeClient = ref.read(pinnedClientFactoryProvider)(seen);
          final PairingInfo info;
          try {
            info = await UltronApi(baseUrl: url, tokens: MemoryTokenStore(), client: probeClient).pairingInfo();
          } finally {
            probeClient.close();
          }
          if (info.fingerprint != seen) {
            throw const ApiException(
              "The certificate doesn't match what ULTRON Core reports. Something on the network may be "
              'intercepting the connection; pairing stopped.',
            );
          }
          if (!mounted || !await _confirmFingerprint(shortFingerprint(seen))) return;
          await settings.setTlsFingerprint(seen);
        }
      }
      if (url != ref.read(settingsProvider).backendUrl) await settings.setBackendUrl(url);
      await ref.read(sessionProvider.notifier).pairWithCode(code: _code.text, deviceName: _device.text);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _confirmFingerprint(String short) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          backgroundColor: UltronColors.surface,
          title: const Text('Check the security code'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Your PC shows a security code next to the pairing code. It must be exactly:'),
              const SizedBox(height: 12),
              SelectableText(
                short,
                key: const Key('fingerprint-short'),
                style: const TextStyle(fontFamily: 'Orbitron', fontSize: 18, letterSpacing: 1.2),
              ),
              const SizedBox(height: 12),
              const Text(
                "If it's different, cancel: something on the network may be pretending to be your PC.",
                style: TextStyle(fontSize: 12.5, color: UltronColors.textSecondary),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            FilledButton(
              key: const Key('confirm-fingerprint'),
              onPressed: () => Navigator.pop(context, true),
              child: const Text('It matches'),
            ),
          ],
        ),
      ) ??
      false;

  Future<void> _signIn() async {
    if (_pairMode) return _pair();
    if (!(_form.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final url = normalizeBackendUrl(_url.text);
      if (url != ref.read(settingsProvider).backendUrl) {
        await ref.read(settingsProvider.notifier).setBackendUrl(url);
      }
      await ref
          .read(sessionProvider.notifier)
          .signIn(email: _email.text, password: _password.text, deviceName: _device.text);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _error = e.statusCode == 401 ? 'Wrong email or password.' : e.message);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: UltronBackground(
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: GlassPanel(
                  glow: true,
                  padding: const EdgeInsets.fromLTRB(28, 32, 28, 28),
                  child: AutofillGroup(
                    child: Form(
                      key: _form,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          const Center(child: UltronLogo(size: 26)),
                          const SizedBox(height: 10),
                          Text('Personal AI assistant', textAlign: TextAlign.center, style: theme.textTheme.labelSmall),
                          const SizedBox(height: 28),
                          TextFormField(
                            key: const Key('backend-url'),
                            controller: _url,
                            decoration: InputDecoration(
                              labelText: 'ULTRON Core address',
                              prefixIcon: const Icon(Icons.dns_outlined),
                              suffixIcon: IconButton(
                                tooltip: 'Test connection',
                                icon: const Icon(Icons.wifi_tethering),
                                onPressed: _busy ? null : _testConnection,
                              ),
                            ),
                            keyboardType: TextInputType.url,
                            validator: (v) => validateBackendUrl(v ?? ''),
                          ),
                          if (_probe != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 6, left: 4),
                              child: Text(
                                _probe!,
                                key: const Key('probe-result'),
                                style: TextStyle(
                                  fontSize: 12,
                                  color: _probeOk ? UltronColors.success : UltronColors.textSecondary,
                                ),
                              ),
                            ),
                          const SizedBox(height: 14),
                          if (_pairMode)
                            TextFormField(
                              key: const Key('pairing-code'),
                              controller: _code,
                              textCapitalization: TextCapitalization.characters,
                              decoration: const InputDecoration(
                                labelText: 'Pairing code',
                                hintText: 'ABCD-EFGH',
                                prefixIcon: Icon(Icons.qr_code_2),
                              ),
                              validator: (v) => (v ?? '').replaceAll(RegExp(r'[^A-Za-z0-9]'), '').length >= 6
                                  ? null
                                  : 'Enter the code shown on your signed-in device',
                              onFieldSubmitted: (_) => _signIn(),
                            ),
                          if (!_pairMode) ...[
                            TextFormField(
                              key: const Key('email'),
                              controller: _email,
                              autofillHints: const [AutofillHints.email],
                              keyboardType: TextInputType.emailAddress,
                              decoration: const InputDecoration(
                                labelText: 'Email',
                                prefixIcon: Icon(Icons.alternate_email),
                              ),
                              validator: (v) => (v ?? '').contains('@') ? null : 'Enter your email',
                            ),
                            const SizedBox(height: 14),
                            TextFormField(
                              key: const Key('password'),
                              controller: _password,
                              obscureText: !_showPassword,
                              autofillHints: const [AutofillHints.password],
                              decoration: InputDecoration(
                                labelText: 'Password',
                                prefixIcon: const Icon(Icons.lock_outline),
                                suffixIcon: IconButton(
                                  tooltip: _showPassword ? 'Hide password' : 'Show password',
                                  icon: Icon(_showPassword ? Icons.visibility_off : Icons.visibility),
                                  onPressed: () => setState(() => _showPassword = !_showPassword),
                                ),
                              ),
                              validator: (v) => (v ?? '').isEmpty ? 'Enter your password' : null,
                              onFieldSubmitted: (_) => _signIn(),
                            ),
                          ],
                          const SizedBox(height: 14),
                          TextFormField(
                            key: const Key('device-name'),
                            controller: _device,
                            decoration: const InputDecoration(
                              labelText: 'This device',
                              prefixIcon: Icon(Icons.devices_outlined),
                            ),
                          ),
                          if (_error != null) ...[
                            const SizedBox(height: 16),
                            Text(
                              _error!,
                              key: const Key('login-error'),
                              style: const TextStyle(color: UltronColors.danger),
                            ),
                          ],
                          const SizedBox(height: 24),
                          FilledButton(
                            key: const Key('sign-in'),
                            onPressed: _busy ? null : _signIn,
                            child: _busy
                                ? const SizedBox(
                                    height: 18,
                                    width: 18,
                                    child: CircularProgressIndicator(strokeWidth: 2),
                                  )
                                : Text(_pairMode ? 'PAIR THIS DEVICE' : 'SIGN IN'),
                          ),
                          TextButton(
                            key: const Key('use-pairing'),
                            onPressed: _busy ? null : () => setState(() => _pairMode = !_pairMode),
                            child: Text(
                              _pairMode ? 'Sign in with email and password instead' : 'Pair with a code instead',
                            ),
                          ),
                          const SizedBox(height: 14),
                          Text(
                            'The owner account is created on the PC with:\n'
                            'docker compose exec core ultron-core create-owner --email you@example.com',
                            textAlign: TextAlign.center,
                            style: theme.textTheme.labelSmall?.copyWith(letterSpacing: 0.2),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
