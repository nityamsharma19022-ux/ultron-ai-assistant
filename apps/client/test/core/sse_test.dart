import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:ultron_app/core/api/sse.dart';

Stream<List<int>> chunks(List<String> parts) => Stream.fromIterable(parts.map(utf8.encode));

void main() {
  test('parses events and ignores keep-alive comments', () async {
    final events = await parseSse(
      chunks([
        'event: status\ndata: {"phase": "routing"}\n\n',
        ': keep-alive\n\n',
        'event: delta\ndata: {"text": "Hi"}\n\n',
      ]),
    ).toList();
    expect(events.map((e) => e.event), ['status', 'delta']);
    expect(events.last.json['text'], 'Hi');
  });

  test('handles events split across network chunks', () async {
    final events = await parseSse(chunks(['event: del', 'ta\ndata: {"te', 'xt": "a"}\n', '\n'])).toList();
    expect(events.single.event, 'delta');
    expect(events.single.json, {'text': 'a'});
  });

  test('joins multi-line data and flushes the last event', () async {
    final events = await parseSse(chunks(['data: one\ndata: two'])).toList();
    expect(events.single.event, 'message');
    expect(events.single.data, 'one\ntwo');
  });

  test('handles CRLF line endings and multi-byte characters', () async {
    final events = await parseSse(chunks(['event: delta\r\ndata: {"text": "नमस्ते ✓"}\r\n\r\n'])).toList();
    expect(events.single.json['text'], 'नमस्ते ✓');
  });
}
