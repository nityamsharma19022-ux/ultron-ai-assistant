import 'dart:convert';

/// One Server-Sent Event.
class SseEvent {
  const SseEvent(this.event, this.data);
  final String event;
  final String data;

  Map<String, dynamic> get json => jsonDecode(data) as Map<String, dynamic>;
}

/// Parses a Server-Sent Events byte stream. Comment lines (": keep-alive")
/// are ignored; multi-line `data:` fields are joined with newlines.
Stream<SseEvent> parseSse(Stream<List<int>> bytes) async* {
  var event = 'message';
  final data = <String>[];
  await for (final line in bytes.transform(utf8.decoder).transform(const LineSplitter())) {
    if (line.isEmpty) {
      if (data.isNotEmpty) yield SseEvent(event, data.join('\n'));
      event = 'message';
      data.clear();
      continue;
    }
    if (line.startsWith(':')) continue;
    final colon = line.indexOf(':');
    final field = colon == -1 ? line : line.substring(0, colon);
    var value = colon == -1 ? '' : line.substring(colon + 1);
    if (value.startsWith(' ')) value = value.substring(1);
    if (field == 'event') {
      event = value;
    } else if (field == 'data') {
      data.add(value);
    }
  }
  if (data.isNotEmpty) yield SseEvent(event, data.join('\n'));
}
