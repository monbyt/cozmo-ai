import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

typedef LiveEventHandler = void Function(Map<String, dynamic> event);

class LiveClient {
  LiveClient({required this.backendWsBase});

  final String backendWsBase;
  WebSocketChannel? _channel;
  StreamSubscription? _sub;
  LiveEventHandler? onEvent;
  bool ready = false;

  Future<void> connect({
    required String country,
    required String currency,
    required LiveEventHandler onEvent,
  }) async {
    this.onEvent = onEvent;
    ready = false;
    final base = backendWsBase.trim().replaceAll(RegExp(r'/$'), '');
    final uri = Uri.parse('$base/ws/live');
    try {
      _channel = IOWebSocketChannel.connect(
        uri,
        pingInterval: const Duration(seconds: 20),
        connectTimeout: const Duration(seconds: 12),
      );
      await _channel!.ready;
    } catch (e) {
      throw StateError(
        'Cannot reach $uri — check network / live backend ($e)',
      );
    }
    _sub = _channel!.stream.listen(
      (raw) {
        try {
          final msg = jsonDecode(raw as String) as Map<String, dynamic>;
          if (msg['type'] == 'ready') ready = true;
          onEvent(msg);
        } catch (_) {}
      },
      onDone: () => ready = false,
      onError: (_) => ready = false,
    );
    send({
      'type': 'start',
      'country': country,
      'currency': currency,
      'device': 'flutter-arkit',
    });
  }

  void send(Map<String, dynamic> payload) {
    _channel?.sink.add(jsonEncode(payload));
  }

  void sendAudioPcm16(Uint8List pcm) {
    if (!ready || pcm.isEmpty) return;
    send({'type': 'audio', 'data': base64Encode(pcm)});
  }

  void sendJpegFrame(Uint8List jpegBytes) {
    if (!ready || jpegBytes.isEmpty) return;
    send({'type': 'video', 'data': base64Encode(jpegBytes)});
  }

  void sendPlane({
    required String kind,
    required double areaM2,
    required double widthM,
    required double heightM,
  }) {
    if (!ready) return;
    send({
      'type': 'plane',
      'kind': kind,
      'area_m2': areaM2,
      'width_m': widthM,
      'height_m': heightM,
    });
  }

  void sendText(String text) {
    if (text.trim().isEmpty) return;
    send({
      'type': 'text',
      'text': text,
      'id': DateTime.now().microsecondsSinceEpoch.toString(),
    });
  }

  /// Ask backend + agent to finalize packet and speak the rubric summary.
  void endSweep() {
    send({'type': 'end_sweep'});
    sendText(
      "I'm done with the sweep. Call sync_inventory now and read the summary.",
    );
  }

  Future<void> close() async {
    try {
      send({'type': 'close'});
    } catch (_) {}
    await _sub?.cancel();
    await _channel?.sink.close();
    _channel = null;
    ready = false;
  }
}
