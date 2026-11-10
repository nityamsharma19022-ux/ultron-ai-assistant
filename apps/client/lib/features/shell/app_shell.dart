import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/session.dart';
import '../../core/status/system_status.dart';
import '../../core/theme/ultron_colors.dart';
import '../../widgets/connection_indicator.dart';
import '../../widgets/ultron_background.dart';
import '../../widgets/ultron_logo.dart';
import '../settings/ai_preferences_controller.dart';
import '../voice/voice_controller.dart';
import 'sections.dart';

/// Width at which the sidebar replaces the bottom navigation bar.
const kWideLayoutBreakpoint = 900.0;

/// Main layout: sidebar on wide screens (Windows, tablets), bottom
/// navigation on phones. [pages] supplies the content for each section.
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.pages});
  final Map<AppSection, Widget> pages;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final section = ref.watch(sectionProvider);
    // Load AI preferences at sign-in so "private by default" applies to the
    // first new chat, not only after Settings is opened.
    ref.listen(aiPreferencesProvider, (_, _) {});
    // Voice runs app-wide (it reads finished replies aloud) and reports
    // problems as snack bars.
    ref.listen(voiceProvider.select((v) => v.noticeId), (_, _) {
      final notice = ref.read(voiceProvider).notice;
      if (notice != null) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(content: Text(notice)));
      }
    });
    final page = AnimatedSwitcher(
      duration: const Duration(milliseconds: 260),
      switchInCurve: Curves.easeOutCubic,
      child: KeyedSubtree(key: ValueKey(section), child: pages[section] ?? const SizedBox()),
    );
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= kWideLayoutBreakpoint;
        return Scaffold(
          body: UltronBackground(
            child: SafeArea(
              child: Column(
                children: [
                  const _OfflineBanner(),
                  if (!wide) const _TopBar(),
                  Expanded(
                    child: wide
                        ? Row(
                            children: [
                              const _Sidebar(),
                              Expanded(child: page),
                            ],
                          )
                        : page,
                  ),
                ],
              ),
            ),
          ),
          bottomNavigationBar: wide
              ? null
              : NavigationBar(
                  key: const Key('bottom-nav'),
                  backgroundColor: UltronColors.backgroundAlt,
                  selectedIndex: section.index,
                  onDestinationSelected: (i) => ref.read(sectionProvider.notifier).select(AppSection.values[i]),
                  destinations: [
                    for (final s in AppSection.values)
                      NavigationDestination(icon: Icon(s.icon), selectedIcon: Icon(s.selectedIcon), label: s.label),
                  ],
                ),
        );
      },
    );
  }
}

class _Sidebar extends ConsumerWidget {
  const _Sidebar();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final section = ref.watch(sectionProvider);
    final session = ref.watch(sessionProvider);
    final accent = Theme.of(context).colorScheme.primary;
    return Container(
      key: const Key('sidebar'),
      width: 236,
      decoration: BoxDecoration(
        color: UltronColors.backgroundAlt.withValues(alpha: 0.75),
        border: Border(right: BorderSide(color: accent.withValues(alpha: 0.15))),
      ),
      padding: const EdgeInsets.fromLTRB(16, 22, 16, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const UltronLogo(size: 18),
          const SizedBox(height: 32),
          for (final s in AppSection.values)
            _NavItem(section: s, selected: s == section, onTap: () => ref.read(sectionProvider.notifier).select(s)),
          const Spacer(),
          const ConnectionIndicator(),
          const SizedBox(height: 16),
          if (session is SignedIn)
            Text(
              '${session.me.user.name} · ${session.me.device.name}',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelSmall,
            ),
        ],
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.section, required this.selected, required this.onTap});
  final AppSection section;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          key: Key('nav-${section.name}'),
          borderRadius: BorderRadius.circular(12),
          onTap: onTap,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 220),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              color: selected ? accent.withValues(alpha: 0.12) : Colors.transparent,
              border: Border.all(color: selected ? accent.withValues(alpha: 0.45) : Colors.transparent),
            ),
            child: Row(
              children: [
                Icon(
                  selected ? section.selectedIcon : section.icon,
                  size: 20,
                  color: selected ? accent : UltronColors.textSecondary,
                ),
                const SizedBox(width: 12),
                Text(
                  section.label,
                  style: TextStyle(
                    color: selected ? UltronColors.textPrimary : UltronColors.textSecondary,
                    fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Thin banner shown while the backend is unreachable.
class _OfflineBanner extends ConsumerWidget {
  const _OfflineBanner();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(systemStatusProvider);
    final show = status.link == BackendLink.offline;
    return AnimatedSize(
      duration: const Duration(milliseconds: 250),
      child: show
          ? Container(
              key: const Key('offline-banner'),
              width: double.infinity,
              color: UltronColors.danger.withValues(alpha: 0.15),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  const Icon(Icons.cloud_off, size: 16, color: UltronColors.danger),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      status.error ?? 'ULTRON Core is offline.',
                      style: const TextStyle(fontSize: 12, color: UltronColors.textPrimary),
                    ),
                  ),
                  TextButton(
                    onPressed: () => ref.read(systemStatusProvider.notifier).refresh(),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            )
          : const SizedBox(width: double.infinity),
    );
  }
}

/// Phone-width header: logo plus the compact cloud/local indicator.
class _TopBar extends StatelessWidget {
  const _TopBar();

  @override
  Widget build(BuildContext context) => Container(
    key: const Key('top-bar'),
    padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
    decoration: BoxDecoration(
      border: Border(bottom: BorderSide(color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.12))),
    ),
    child: const Row(children: [UltronLogo(size: 15), Spacer(), ConnectionIndicator(compact: true)]),
  );
}
