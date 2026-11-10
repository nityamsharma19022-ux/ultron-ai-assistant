import 'package:flutter_riverpod/flutter_riverpod.dart';

/// App-wide short messages (shown as snack bars by the shell).
class Notice {
  const Notice(this.id, this.text);
  final int id;
  final String text;
}

final noticesProvider = NotifierProvider<NoticesController, Notice?>(NoticesController.new);

class NoticesController extends Notifier<Notice?> {
  int _next = 0;
  @override
  Notice? build() => null;
  void show(String text) => state = Notice(++_next, text);
}
