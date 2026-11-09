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
  bool _busy = false;
  bool _showPassword = false;
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
    for (final c in [_url, _email, _password, _device]) {
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

  Future<void> _signIn() async {
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
                          Text(
                            'Personal AI assistant',
                            textAlign: TextAlign.center,
                            style: theme.textTheme.labelSmall,
                          ),
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
                                : const Text('SIGN IN'),
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
