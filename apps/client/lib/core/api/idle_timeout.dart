import 'dart:async';

/// Forwards [source] and fails with [onIdle]'s error if no data arrives for
/// [limit]. The backend sends keep-alives every few seconds while it is
/// working, so a long silence means the connection is gone.
Stream<T> withIdleTimeout<T>(Stream<T> source, Duration limit, Object Function() onIdle) {
  late final StreamController<T> controller;
  StreamSubscription<T>? subscription;
  Timer? timer;
  var finished = false;

  void arm() {
    timer?.cancel();
    timer = Timer(limit, () {
      finished = true;
      controller.addError(onIdle());
      subscription?.cancel();
      controller.close();
    });
  }

  controller = StreamController<T>(
    onListen: () {
      arm();
      subscription = source.listen(
        (data) {
          arm();
          controller.add(data);
        },
        onError: controller.addError,
        onDone: () {
          finished = true;
          timer?.cancel();
          controller.close();
        },
      );
    },
    onPause: () {
      timer?.cancel();
      subscription?.pause();
    },
    onResume: () {
      subscription?.resume();
      arm();
    },
    onCancel: () {
      timer?.cancel();
      // Once the source has finished (or we gave up on it) there is nothing
      // left to cancel, and returning its cancel future would only delay
      // the "done" signal to our listener.
      if (finished) return null;
      return subscription?.cancel();
    },
  );
  return controller.stream;
}
