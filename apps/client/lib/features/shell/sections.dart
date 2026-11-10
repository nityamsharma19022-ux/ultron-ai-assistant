import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

enum AppSection {
  home('Home', Icons.space_dashboard_outlined, Icons.space_dashboard),
  chat('Chat', Icons.forum_outlined, Icons.forum),
  tasks('Tasks', Icons.bolt_outlined, Icons.bolt),
  memory('Memory', Icons.psychology_outlined, Icons.psychology),
  dashboard('System', Icons.monitor_heart_outlined, Icons.monitor_heart),
  settings('Settings', Icons.tune_outlined, Icons.tune);

  const AppSection(this.label, this.icon, this.selectedIcon);
  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

final sectionProvider = NotifierProvider<SectionController, AppSection>(SectionController.new);

class SectionController extends Notifier<AppSection> {
  @override
  AppSection build() => AppSection.home;
  void select(AppSection s) => state = s;
}
