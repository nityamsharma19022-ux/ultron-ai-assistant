import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/settings/ai_preferences_controller.dart';

/// 12-hour time (9:30 PM) is the default everywhere; 24-hour is optional and
/// saved on ULTRON Core, so every device uses the same choice.
final use24HourProvider = Provider<bool>(
  (ref) => ref.watch(aiPreferencesProvider.select((p) => p.value?.timeFormat == '24h')),
);

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// 12:05 AM after midnight, 12:00 PM at noon.
String clockText(int hour, int minute, {bool h24 = false}) {
  final m = minute.toString().padLeft(2, '0');
  if (h24) return '${hour.toString().padLeft(2, '0')}:$m';
  final h = hour % 12 == 0 ? 12 : hour % 12;
  return '$h:$m ${hour < 12 ? 'AM' : 'PM'}';
}

/// Local time of [t] (stored times are converted to this device's zone).
String timeText(DateTime t, {bool h24 = false}) {
  final l = t.toLocal();
  return clockText(l.hour, l.minute, h24: h24);
}

/// "22:00" (as stored) -> "10:00 PM".
String hhmmText(String? value, {bool h24 = false}) {
  if (value == null || !value.contains(':')) return value ?? '';
  final p = value.split(':');
  return clockText(int.parse(p[0]), int.parse(p[1]), h24: h24);
}

/// "Today 9:30 PM", "Tomorrow 7:00 AM", "Yesterday 6:15 PM" or "12 Nov 6:15 PM".
String dayTimeText(DateTime t, {bool h24 = false, DateTime? now}) {
  final l = t.toLocal();
  final n = (now ?? DateTime.now()).toLocal();
  final days = DateTime(l.year, l.month, l.day).difference(DateTime(n.year, n.month, n.day)).inDays;
  final time = clockText(l.hour, l.minute, h24: h24);
  return switch (days) {
    0 => 'Today $time',
    1 => 'Tomorrow $time',
    -1 => 'Yesterday $time',
    _ => '${l.day} ${_months[l.month - 1]}${l.year != n.year ? ' ${l.year}' : ''} $time',
  };
}
