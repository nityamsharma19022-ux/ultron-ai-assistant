import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/auth/session.dart';
import 'core/settings/app_settings.dart';
import 'core/theme/ultron_theme.dart';
import 'features/auth/login_screen.dart';
import 'features/chat/chat_page.dart';
import 'features/dashboard/dashboard_page.dart';
import 'features/settings/settings_page.dart';
import 'features/shell/app_shell.dart';
import 'features/shell/sections.dart';
import 'features/visualizer/chat_visualizer.dart';
import 'widgets/glass_panel.dart';
import 'widgets/ultron_background.dart';
import 'widgets/ultron_logo.dart';

class UltronApp extends ConsumerWidget {
  const UltronApp({super.key, this.pages});

  /// Section pages; defaults to the real screens. Tests can replace them.
  final Map<AppSection, Widget>? pages;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accent = ref.watch(settingsProvider.select((s) => s.accent));
    final session = ref.watch(sessionProvider);
    return MaterialApp(
      title: 'ULTRON',
      debugShowCheckedModeBanner: false,
      theme: buildUltronTheme(accent.color),
      home: AnimatedSwitcher(
        duration: const Duration(milliseconds: 400),
        child: switch (session) {
          SessionChecking() => const _Splash(key: ValueKey('splash')),
          SignedOut(:final message) => LoginScreen(key: const ValueKey('login'), message: message),
          BackendUnreachable(:final message) => _Unreachable(key: const ValueKey('unreachable'), message: message),
          SignedIn() => AppShell(key: const ValueKey('shell'), pages: pages ?? defaultPages()),
        },
      ),
    );
  }
}

/// The real section pages.
Map<AppSection, Widget> defaultPages() => {
  AppSection.chat: ChatPage(
    heroBuilder: (context, state, size) => ChatVisualizer(size: size),
    headerOrbBuilder: (context, state, size) => ChatVisualizer(size: size),
  ),
  AppSection.dashboard: const DashboardPage(),
  AppSection.settings: const SettingsPage(),
};

class _Splash extends StatelessWidget {
  const _Splash({super.key});

  @override
  Widget build(BuildContext context) => const Scaffold(
    body: UltronBackground(child: Center(child: UltronLogo(size: 28))),
  );
}

class _Unreachable extends ConsumerWidget {
  const _Unreachable({super.key, required this.message});
  final String message;

  @override
  Widget build(BuildContext context, WidgetRef ref) => Scaffold(
    body: UltronBackground(
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: GlassPanel(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const UltronLogo(size: 20),
                const SizedBox(height: 20),
                Text(message, textAlign: TextAlign.center),
                const SizedBox(height: 20),
                Wrap(
                  spacing: 12,
                  children: [
                    FilledButton(
                      onPressed: () => ref.read(sessionProvider.notifier).restore(),
                      child: const Text('RETRY'),
                    ),
                    OutlinedButton(
                      onPressed: () => ref.read(sessionProvider.notifier).signOut(),
                      child: const Text('CHANGE SERVER'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
