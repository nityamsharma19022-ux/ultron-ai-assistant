import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/api/idle_timeout.dart';

void main() {
  testWidgets('forwards data and completes when the source completes', (tester) async {
    final source = StreamController<int>();
    final seen = <int>[];
    var done = false;
    withIdleTimeout(
      source.stream,
      const Duration(seconds: 5),
      () => 'idle',
    ).listen(seen.add, onDone: () => done = true);
    source
      ..add(1)
      ..add(2);
    unawaited(source.close());
    await tester.pump(const Duration(milliseconds: 10));
    expect(seen, [1, 2]);
    expect(done, isTrue);
  });

  testWidgets('reports an error and closes after a long silence', (tester) async {
    final source = StreamController<int>();
    final errors = <Object>[];
    var done = false;
    withIdleTimeout(
      source.stream,
      const Duration(seconds: 5),
      () => 'idle',
    ).listen((_) {}, onError: errors.add, onDone: () => done = true);
    source.add(1);
    await tester.pump(const Duration(seconds: 4));
    expect(errors, isEmpty);
    source.add(2); // activity resets the timer
    await tester.pump(const Duration(seconds: 4));
    expect(errors, isEmpty);
    await tester.pump(const Duration(seconds: 6));
    expect(errors, ['idle']);
    expect(done, isTrue);
    expect(source.hasListener, isFalse);
  });

  testWidgets('cancelling stops the timer and the source', (tester) async {
    final source = StreamController<int>();
    final sub = withIdleTimeout(source.stream, const Duration(seconds: 5), () => 'idle').listen((_) {});
    await tester.pump();
    unawaited(sub.cancel());
    await tester.pump(const Duration(seconds: 10)); // no pending-timer failure
    expect(source.hasListener, isFalse);
  });
}
