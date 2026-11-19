import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:arkit_plugin/arkit_plugin.dart';
import 'package:collection/collection.dart';
import 'package:cozmo_sweep/models/inventory.dart';
import 'package:cozmo_sweep/services/frame_encode.dart';
import 'package:cozmo_sweep/services/live_client.dart';
import 'package:cozmo_sweep/services/voice_io.dart';
import 'package:cozmo_sweep/widgets/inventory_carousel.dart';
import 'package:cozmo_sweep/widgets/item_detail_sheet.dart';
import 'package:cozmo_sweep/widgets/room_map.dart';
import 'package:cozmo_sweep/widgets/sweep_summary_sheet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:vector_math/vector_math_64.dart' as vector;

enum _BootPhase { idle, connecting, waitingAgent, startingMic, ready, failed }

/// Minimal AR sweep: feature dots, go-back trail, live inventory + room map.
class ArGuidanceScreen extends StatefulWidget {
  const ArGuidanceScreen({
    super.key,
    required this.backendWsBase,
    this.country = 'US',
    this.currency = 'USD',
  });

  final String backendWsBase;
  final String country;
  final String currency;

  @override
  State<ArGuidanceScreen> createState() => _ArGuidanceScreenState();
}

class _ArGuidanceScreenState extends State<ArGuidanceScreen> {
  ARKitController? _controller;
  LiveClient? _live;
  final _voice = VoiceIo();

  _BootPhase _phase = _BootPhase.idle;
  String _status = 'Point at shelves. Tap Start when ready.';
  String _agentLine = '';
  String _banner = '';
  String _bootDetail = '';
  String _logFlash = '';
  int _logFlashToken = 0;

  final List<InvBook> _books = [];
  final List<InvItem> _items = [];
  /// Newest-first combined feed for the on-screen log list.
  final List<Object> _logFeed = [];
  final List<RoomPlaneMark> _planes = [];
  final RoomStats _room = RoomStats();
  final Set<String> _sentPlanes = {};
  Map<String, dynamic>? _lastSummary;
  String? _packetJsonUrl;
  String? _packetHtmlUrl;
  Completer<Map<String, dynamic>?>? _summaryWait;

  vector.Vector3? _lastLookAt;

  Timer? _frameTimer;
  bool _capturing = false;
  bool _encoding = false;
  Uint8List? _pendingRawFrame;
  bool _ending = false;

  bool get _running => _phase == _BootPhase.ready;
  bool get _booting =>
      _phase == _BootPhase.connecting ||
      _phase == _BootPhase.waitingAgent ||
      _phase == _BootPhase.startingMic;

  @override
  void dispose() {
    _frameTimer?.cancel();
    unawaited(_shutdown());
    super.dispose();
  }

  Future<void> _shutdown() async {
    _frameTimer?.cancel();
    await _voice.stop();
    await _live?.close();
    _live = null;
    _controller?.dispose();
    _controller = null;
  }

  String get _bootLabel {
    switch (_phase) {
      case _BootPhase.connecting:
        return 'Connecting to backend…';
      case _BootPhase.waitingAgent:
        return 'Loading live agent…';
      case _BootPhase.startingMic:
        return 'Starting microphone…';
      case _BootPhase.failed:
        return 'Failed to start';
      default:
        return '';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          ARKitSceneView(
            configuration: ARKitConfiguration.worldTracking,
            planeDetection: ARPlaneDetection.horizontalAndVertical,
            showFeaturePoints: false,
            enableTapRecognizer: false,
            autoenablesDefaultLighting: true,
            onARKitViewCreated: (c) {
              _controller = c;
              c.onAddNodeForAnchor = _onAnchor;
            },
          ),

          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
              child: Column(
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      IconButton.filledTonal(
                        onPressed: () async {
                          await _stop();
                          if (context.mounted) Navigator.of(context).maybePop();
                        },
                        icon: const Icon(Icons.close),
                      ),
                      const Spacer(),
                      if (_running) ...[
                        Container(
                          margin: const EdgeInsets.only(right: 8),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 7,
                          ),
                          decoration: BoxDecoration(
                            color: const Color(0xFF1B3D2F),
                            borderRadius: BorderRadius.circular(999),
                            border: Border.all(color: const Color(0xFF3DCF8E)),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Container(
                                width: 8,
                                height: 8,
                                decoration: const BoxDecoration(
                                  color: Color(0xFF3DCF8E),
                                  shape: BoxShape.circle,
                                ),
                              ),
                              const SizedBox(width: 6),
                              Text(
                                'LOGGING  ${_books.length + _items.length}',
                                style: const TextStyle(
                                  color: Color(0xFFB8F0C0),
                                  fontSize: 11,
                                  fontWeight: FontWeight.w800,
                                  letterSpacing: 0.4,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                      RoomMapChip(
                        stats: _room,
                        onTap: () => showRoomMapSheet(
                          context: context,
                          planes: _planes,
                          books: _books,
                          items: _items,
                          stats: _room,
                          onOpenEntry: (e) => showInventoryDetail(context, e),
                        ),
                      ),
                    ],
                  ),

                  if (_logFlash.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 10,
                      ),
                      decoration: BoxDecoration(
                        color: const Color(0xFF1B3D2F),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: const Color(0xFF3DCF8E)),
                      ),
                      child: Text(
                        _logFlash,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: Color(0xFFB8F0C0),
                          fontWeight: FontWeight.w800,
                          fontSize: 14,
                        ),
                      ),
                    ),
                  ],

                  if (_banner.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFFC107),
                        borderRadius: BorderRadius.circular(14),
                      ),
                      child: Text(
                        _banner,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: Colors.black,
                          fontWeight: FontWeight.w800,
                          fontSize: 15,
                        ),
                      ),
                    ),
                  ],

                  const Spacer(),

                  if (_agentLine.isNotEmpty)
                    Container(
                      width: double.infinity,
                      margin: const EdgeInsets.only(bottom: 8),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: Colors.black.withValues(alpha: 0.55),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        _agentLine,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(color: Colors.white, fontSize: 13),
                      ),
                    ),

                  InventoryLogFeed(
                    entries: _logFeed,
                    onOpen: (e) => showInventoryDetail(context, e),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _status,
                    style: const TextStyle(color: Colors.white70, fontSize: 11),
                  ),
                  const SizedBox(height: 8),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: (_booting || _ending)
                          ? null
                          : (_running ? _endSweep : _start),
                      style: FilledButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        backgroundColor: _running
                            ? const Color(0xFFE5556B)
                            : const Color(0xFF7C8CFF),
                      ),
                      child: Text(
                        _booting
                            ? 'Loading…'
                            : (_ending
                                ? 'Building packet…'
                                : (_running ? 'End sweep' : 'Start sweep')),
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),

          if (_booting || _phase == _BootPhase.failed)
            Container(
              color: Colors.black.withValues(alpha: 0.72),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 320),
                  child: Container(
                    margin: const EdgeInsets.all(24),
                    padding: const EdgeInsets.all(22),
                    decoration: BoxDecoration(
                      color: const Color(0xFF16181F),
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(color: Colors.white12),
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (_phase != _BootPhase.failed)
                          const SizedBox(
                            width: 36,
                            height: 36,
                            child: CircularProgressIndicator(strokeWidth: 3),
                          )
                        else
                          const Icon(Icons.error_outline,
                              color: Color(0xFFE5556B), size: 36),
                        const SizedBox(height: 16),
                        Text(
                          _bootLabel,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w800,
                            fontSize: 17,
                          ),
                        ),
                        if (_bootDetail.isNotEmpty) ...[
                          const SizedBox(height: 8),
                          Text(
                            _bootDetail,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              color: Colors.white60,
                              fontSize: 13,
                            ),
                          ),
                        ],
                        if (_phase == _BootPhase.waitingAgent) ...[
                          const SizedBox(height: 10),
                          const Text(
                            'Gemini Live can take 10–30s on first connect.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: Colors.white38,
                              fontSize: 12,
                            ),
                          ),
                        ],
                        if (_phase == _BootPhase.failed) ...[
                          const SizedBox(height: 16),
                          FilledButton(
                            onPressed: _start,
                            child: const Text('Retry'),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  void _onAnchor(ARKitAnchor anchor) {
    if (anchor is! ARKitPlaneAnchor) return;
    if (_sentPlanes.contains(anchor.identifier)) return;
    _sentPlanes.add(anchor.identifier);

    final w = anchor.extent.x.abs();
    final d = anchor.extent.z.abs();
    final area = w * d;
    if (area < 0.15) return;

    final origin = anchor.transform.getTranslation();
    final centerLocal = anchor.center;
    final cx = origin.x + centerLocal.x;
    final cz = origin.z + centerLocal.z;

    final up = anchor.transform.getColumn(1);
    final isFloor = up.y.abs() > 0.75;
    final kind = isFloor ? 'floor' : 'wall';
    final widthM = isFloor ? math.max(w, d) : w;
    final heightOrDepth = isFloor ? math.min(w, d) : d;

    _planes.add(RoomPlaneMark(
      id: anchor.identifier,
      kind: kind,
      cx: cx,
      cz: cz,
      widthM: widthM,
      depthM: heightOrDepth,
      areaM2: area,
    ));
    _recomputeRoom();
    // Don't rebuild the whole AR HUD for every plane — chip label only.
    if (mounted) setState(() {});

    _live?.sendPlane(
      kind: kind,
      areaM2: area,
      widthM: widthM,
      heightM: heightOrDepth,
    );
  }

  void _recomputeRoom() {
    final floors = _planes.where((p) => p.kind == 'floor').toList();
    final walls = _planes.where((p) => p.kind == 'wall').toList();
    if (floors.isNotEmpty) {
      final f = floors.reduce((a, b) => a.areaM2 >= b.areaM2 ? a : b);
      _room.floorAreaM2 = f.areaM2;
      _room.lengthM = math.max(f.widthM, f.depthM);
      _room.widthM = math.min(f.widthM, f.depthM);
    }
    _room.wallAreaM2 = walls.fold(0.0, (s, p) => s + p.areaM2);
    if (walls.isNotEmpty) {
      final hs = walls.map((w) => w.depthM).where((h) => h > 0.5).toList()
        ..sort();
      if (hs.isNotEmpty) _room.heightM = hs[hs.length ~/ 2];
    }
    _room.scaleMethod = 'arkit_plane_detection';
  }

  Future<void> _start() async {
    if (_controller == null) {
      setState(() {
        _phase = _BootPhase.failed;
        _bootDetail = 'AR not ready yet — wait a second and retry.';
      });
      return;
    }
    setState(() {
      _phase = _BootPhase.connecting;
      _bootDetail = 'Opening WebSocket ${widget.backendWsBase}';
      _books.clear();
      _items.clear();
      _logFeed.clear();
      _status = 'Starting…';
    });
    try {
      final live = LiveClient(backendWsBase: widget.backendWsBase);
      setState(() {
        _phase = _BootPhase.waitingAgent;
        _bootDetail = 'Waiting for Gemini Live session (this is the slow part)…';
      });
      await live.connect(
        country: widget.country,
        currency: widget.currency,
        onEvent: _onLiveEvent,
      );
      // Wait until server sends ready (connect returns after WS open + start send).
      final deadline = DateTime.now().add(const Duration(seconds: 45));
      while (!live.ready && DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(milliseconds: 200));
      }
      if (!live.ready) {
        throw StateError('Agent timed out — check backend / API key');
      }
      _live = live;

      setState(() {
        _phase = _BootPhase.startingMic;
        _bootDetail = 'Mic + speaker routing…';
      });
      await _voice.start(onMicPcm: (pcm) {
        _live?.sendAudioPcm16(pcm);
      });

      // Capture fast; encode/send latest frame in background (drops backlog).
      _frameTimer = Timer.periodic(const Duration(milliseconds: 320), (_) {
        unawaited(_captureFrame());
      });

      setState(() {
        _phase = _BootPhase.ready;
        _bootDetail = '';
        _status = 'Walk fast — capturing now, pricing fills in behind';
      });
    } catch (e) {
      await _voice.stop();
      await _live?.close();
      _live = null;
      setState(() {
        _phase = _BootPhase.failed;
        _bootDetail = '$e';
        _status = 'Failed to start';
      });
    }
  }

  Future<void> _endSweep() async {
    if (_ending) return;
    setState(() {
      _ending = true;
      _status = 'Finishing packet + summary…';
    });
    _frameTimer?.cancel();
    final live = _live;
    final wait = Completer<Map<String, dynamic>?>();
    _summaryWait = wait;
    live?.endSweep();

    // Keep mic/speaker briefly so the agent can read the summary aloud.
    Map<String, dynamic>? summary;
    try {
      summary = await wait.future.timeout(
        const Duration(seconds: 25),
        onTimeout: () => _lastSummary,
      );
    } catch (_) {
      summary = _lastSummary;
    }

    // Brief pause so spoken summary can finish, then tear down.
    await Future<void>.delayed(const Duration(seconds: 2));
    await _voice.stop();
    await _live?.close();
    _live = null;
    _summaryWait = null;

    if (!mounted) return;
    setState(() {
      _phase = _BootPhase.idle;
      _ending = false;
      _status = 'Sweep complete';
      _agentLine = '';
      _banner = '';
    });

    final s = summary ?? _fallbackSummary();
    await showSweepSummarySheet(
      context,
      s,
      jsonUrl: _packetJsonUrl,
      htmlUrl: _packetHtmlUrl,
    );
  }

  Map<String, dynamic> _fallbackSummary() {
    final identified =
        _books.where((b) => b.status == 'identified').length;
    final unidentified =
        _books.where((b) => b.status == 'unidentified').length;
    return {
      'book_count': _books.length,
      'books_identified': identified,
      'books_unidentified': unidentified,
      'shelf_run_m': 0,
      'books_replacement_cost': 0,
      'books_used_value': 0,
      'item_count': _items.length,
      'items_replacement_cost_low': 0,
      'items_replacement_cost_high': 0,
      'excluded_from_totals': 0,
      'review_queue_count': 0,
      'room': {
        'length_m': _room.lengthM,
        'width_m': _room.widthM,
        'height_m': _room.heightM,
        'floor_area_m2': _room.floorAreaM2,
        'floor_area_ft2':
            double.parse((_room.floorAreaM2 * 10.7639).toStringAsFixed(1)),
        'wall_area_m2': _room.wallAreaM2,
        'shelved_wall_area_m2': 0,
        'scale_method': _room.scaleMethod,
        'confidence': 0,
      },
      'books_preview': _books
          .take(8)
          .map((b) => {
                'title': b.displayTitle,
                'status': b.status,
                'replacement': b.replacementCost.amount > 0
                    ? b.replacementCost.amount
                    : null,
              })
          .toList(),
      'items_preview': _items
          .take(6)
          .map((i) => {
                'description': i.displayTitle,
                'category': i.category,
                'status': i.status,
              })
          .toList(),
      'speak':
          '${_books.length} books, ${_items.length} items. Floor ${_room.floorAreaM2.toStringAsFixed(1)} m².',
    };
  }

  Future<void> _stop() async {
    _frameTimer?.cancel();
    await _voice.stop();
    await _live?.close();
    _live = null;
    if (mounted) {
      setState(() {
        _phase = _BootPhase.idle;
        _ending = false;
        _status = 'Sweep ended';
        _agentLine = '';
        _banner = '';
        _bootDetail = '';
      });
    }
  }

  void _onLiveEvent(Map<String, dynamic> e) {
    final type = e['type'];
    switch (type) {
      case 'audio':
        _voice.playPcm24Base64((e['data'] as String?) ?? '');
        break;
      case 'interrupted':
        unawaited(_voice.stopPlayback());
        break;
      case 'transcript':
        if (e['speaker'] == 'Agent') {
          final t = (e['text'] as String?) ?? '';
          if (t.isEmpty) break;
          setState(() {
            final next = _agentLine + t;
            _agentLine =
                next.length > 110 ? '…${next.substring(next.length - 110)}' : next;
            if (e['final'] == true) _agentLine = '';
          });
        }
        break;
      case 'revisit':
        final hint = (e['hint'] as String?) ?? '';
        if (hint.isNotEmpty) {
          setState(() => _banner = hint);
          Future.delayed(const Duration(seconds: 4), () {
            if (mounted) setState(() => _banner = '');
          });
        }
        break;
      case 'banner':
        final text = (e['text'] as String?) ?? '';
        if (text.isNotEmpty) {
          setState(() => _banner = text);
          Future.delayed(const Duration(seconds: 3), () {
            if (mounted && _banner == text) setState(() => _banner = '');
          });
        }
        break;
      case 'inventory_update':
        _mergeInventory(e);
        break;
      case 'packet_ready':
        final summary = (e['summary'] is Map)
            ? Map<String, dynamic>.from(e['summary'] as Map)
            : null;
        _lastSummary = summary;
        _packetJsonUrl = e['json_url'] as String?;
        _packetHtmlUrl = e['html_url'] as String?;
        if (_summaryWait != null && !(_summaryWait!.isCompleted)) {
          _summaryWait!.complete(summary);
        }
        if (mounted && summary != null) {
          setState(() => _status = 'Packet ready');
        }
        break;
      case 'error':
        setState(() => _status = '${e['message']}');
        break;
      case 'ready':
        break;
    }
  }

  void _flashLogged(String label) {
    final token = ++_logFlashToken;
    setState(() => _logFlash = 'Logged · $label');
    Future.delayed(const Duration(seconds: 2), () {
      if (!mounted || token != _logFlashToken) return;
      setState(() => _logFlash = '');
    });
  }

  void _mergeInventory(Map<String, dynamic> e) {
    final look = _lastLookAt;
    var changed = false;
    final newlyLogged = <String>[];
    var playedChime = false;
    for (final raw in (e['new_books'] as List?) ?? const []) {
      if (raw is! Map) continue;
      final m = Map<String, dynamic>.from(raw);
      final id = m['id'] as String?;
      if (id == null) continue;
      final existing = _books.firstWhereOrNull((b) => b.id == id);
      if (existing == null) {
        final b = InvBook.fromMap(m);
        if (look != null) {
          b.mapX = look.x;
          b.mapZ = look.z;
        }
        _books.insert(0, b);
        _logFeed.insert(0, b);
        newlyLogged.add(b.displayTitle);
        if (!playedChime) {
          _voice.playLogChime();
          playedChime = true;
        }
      } else {
        existing.merge(m);
      }
      changed = true;
    }
    for (final raw in (e['new_items'] as List?) ?? const []) {
      if (raw is! Map) continue;
      final m = Map<String, dynamic>.from(raw);
      final id = m['id'] as String?;
      if (id == null) continue;
      final existing = _items.firstWhereOrNull((i) => i.id == id);
      if (existing == null) {
        final it = InvItem.fromMap(m);
        if (look != null) {
          it.mapX = look.x;
          it.mapZ = look.z;
        }
        _items.insert(0, it);
        _logFeed.insert(0, it);
        newlyLogged.add(it.displayTitle);
        if (!playedChime) {
          _voice.playLogChime();
          playedChime = true;
        }
      } else {
        existing.merge(m);
      }
      changed = true;
    }
    if (changed && mounted) {
      setState(() {
        _status =
            'Logged ${_books.length} books · ${_items.length} items — keep walking';
      });
      if (newlyLogged.isNotEmpty) {
        _flashLogged(newlyLogged.first);
      }
    }
  }

  /// Grab the latest camera frame quickly; never wait on JPEG encode here.
  Future<void> _captureFrame() async {
    if (_capturing || !_running) return;
    final c = _controller;
    final live = _live;
    if (c == null || live == null || !live.ready) return;
    _capturing = true;
    try {
      final hits = await c.performHitTest(x: 0.5, y: 0.55);
      final hit = hits.firstWhereOrNull(
            (h) => h.type == ARKitHitTestResultType.existingPlaneUsingExtent,
          ) ??
          hits.firstWhereOrNull(
            (h) => h.type == ARKitHitTestResultType.featurePoint,
          );
      if (hit != null) {
        _lastLookAt = hit.worldTransform.getTranslation();
      }

      final img = await c.getCapturedImage();
      if (img is MemoryImage && img.bytes.isNotEmpty) {
        // Keep only the newest raw frame — walking past shelves prefers freshness.
        _pendingRawFrame = img.bytes;
        if (!_encoding) unawaited(_drainEncodeQueue());
      }
    } catch (_) {
    } finally {
      _capturing = false;
    }
  }

  Future<void> _drainEncodeQueue() async {
    if (_encoding) return;
    _encoding = true;
    try {
      while (_pendingRawFrame != null && _running) {
        final raw = _pendingRawFrame!;
        _pendingRawFrame = null;
        final live = _live;
        if (live == null || !live.ready) break;
        try {
          final jpeg = await compute(encodeLiveJpegIsolate, raw);
          if (jpeg != null && jpeg.isNotEmpty) {
            live.sendJpegFrame(jpeg);
          }
        } catch (_) {}
      }
    } finally {
      _encoding = false;
      // A frame may have landed while we were finishing.
      if (_pendingRawFrame != null && _running) {
        unawaited(_drainEncodeQueue());
      }
    }
  }
}
