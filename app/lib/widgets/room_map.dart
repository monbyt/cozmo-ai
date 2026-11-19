import 'dart:math' as math;

import 'package:cozmo_sweep/models/inventory.dart';
import 'package:flutter/material.dart';

/// Compact map affordance — opens the sheet; no big HUD widget.
class RoomMapChip extends StatelessWidget {
  const RoomMapChip({
    super.key,
    required this.stats,
    required this.onTap,
  });

  final RoomStats stats;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final label = stats.floorAreaM2 > 0
        ? '${stats.floorAreaM2.toStringAsFixed(0)} m²'
        : 'Map';
    return Material(
      color: Colors.black.withValues(alpha: 0.45),
      borderRadius: BorderRadius.circular(999),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(999),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.map_outlined, size: 16, color: Colors.white70),
              const SizedBox(width: 6),
              Text(
                label,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

Future<void> showRoomMapSheet({
  required BuildContext context,
  required List<RoomPlaneMark> planes,
  required List<InvBook> books,
  required List<InvItem> items,
  required RoomStats stats,
  required void Function(Object entry) onOpenEntry,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: const Color(0xFF12141A),
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
    ),
    builder: (ctx) {
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: Colors.white24,
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
              ),
              const SizedBox(height: 14),
              const Text(
                'Room',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 12),
              AspectRatio(
                aspectRatio: 1.4,
                child: Container(
                  decoration: BoxDecoration(
                    color: Colors.black,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.white12),
                  ),
                  child: CustomPaint(
                    painter: _RoomPainter(
                      planes: planes,
                      books: books,
                      items: items,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              _stat(
                'Size',
                stats.lengthM > 0
                    ? '${stats.lengthM.toStringAsFixed(1)} × ${stats.widthM.toStringAsFixed(1)} m'
                    : 'scanning…',
              ),
              _stat(
                'Floor',
                stats.floorAreaM2 > 0
                    ? '${stats.floorAreaM2.toStringAsFixed(1)} m²'
                    : '—',
              ),
              _stat(
                'Walls',
                stats.wallAreaM2 > 0
                    ? '${stats.wallAreaM2.toStringAsFixed(1)} m²'
                    : '—',
              ),
              const SizedBox(height: 8),
              SizedBox(
                height: 100,
                child: ListView(
                  children: [
                    ...books.where((b) => b.mapX != null).take(12).map(
                          (b) => ListTile(
                            dense: true,
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(Icons.menu_book,
                                color: Color(0xFF9AA8FF), size: 18),
                            title: Text(
                              b.displayTitle,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                  color: Colors.white, fontSize: 13),
                            ),
                            onTap: () {
                              Navigator.pop(ctx);
                              onOpenEntry(b);
                            },
                          ),
                        ),
                    ...items.where((i) => i.mapX != null).take(8).map(
                          (i) => ListTile(
                            dense: true,
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(Icons.chair_alt,
                                color: Color(0xFF8FCF9A), size: 18),
                            title: Text(
                              i.displayTitle,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                  color: Colors.white, fontSize: 13),
                            ),
                            onTap: () {
                              Navigator.pop(ctx);
                              onOpenEntry(i);
                            },
                          ),
                        ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
    },
  );
}

Widget _stat(String k, String v) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          SizedBox(
            width: 72,
            child: Text(k,
                style: const TextStyle(color: Colors.white54, fontSize: 13)),
          ),
          Expanded(
            child: Text(
              v,
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w600,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );

class _RoomPainter extends CustomPainter {
  _RoomPainter({
    required this.planes,
    required this.books,
    required this.items,
  });

  final List<RoomPlaneMark> planes;
  final List<InvBook> books;
  final List<InvItem> items;

  @override
  void paint(Canvas canvas, Size size) {
    const pad = 16.0;
    final bounds = _bounds();
    if (bounds == null) return;

    final worldW = math.max(bounds.width, 0.5);
    final worldH = math.max(bounds.height, 0.5);
    final scale = math.min(
      (size.width - pad * 2) / worldW,
      (size.height - pad * 2) / worldH,
    );

    Offset map(double x, double z) => Offset(
          pad + (x - bounds.left) * scale,
          pad + (z - bounds.top) * scale,
        );

    final floorPaint = Paint()..color = const Color(0xFF2A3348);
    final wallPaint = Paint()
      ..color = const Color(0xFF6B7CFF)
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke;

    for (final pl in planes) {
      if (pl.kind == 'floor') {
        final r = Rect.fromCenter(
          center: map(pl.cx, pl.cz),
          width: pl.widthM * scale,
          height: pl.depthM * scale,
        );
        canvas.drawRRect(
          RRect.fromRectAndRadius(r, const Radius.circular(4)),
          floorPaint,
        );
      } else {
        final half = pl.widthM / 2;
        canvas.drawLine(
          map(pl.cx - half, pl.cz),
          map(pl.cx + half, pl.cz),
          wallPaint,
        );
      }
    }

    for (final b in books) {
      if (b.mapX == null || b.mapZ == null) continue;
      canvas.drawCircle(map(b.mapX!, b.mapZ!), 3.5, Paint()..color = const Color(0xFF9AA8FF));
    }
    for (final i in items) {
      if (i.mapX == null || i.mapZ == null) continue;
      canvas.drawCircle(map(i.mapX!, i.mapZ!), 3.5, Paint()..color = const Color(0xFF8FCF9A));
    }
  }

  Rect? _bounds() {
    final xs = <double>[];
    final zs = <double>[];
    for (final p in planes) {
      xs.addAll([p.cx - p.widthM / 2, p.cx + p.widthM / 2]);
      zs.addAll([p.cz - p.depthM / 2, p.cz + p.depthM / 2]);
    }
    for (final b in books) {
      if (b.mapX != null) xs.add(b.mapX!);
      if (b.mapZ != null) zs.add(b.mapZ!);
    }
    for (final i in items) {
      if (i.mapX != null) xs.add(i.mapX!);
      if (i.mapZ != null) zs.add(i.mapZ!);
    }
    if (xs.isEmpty || zs.isEmpty) return null;
    return Rect.fromLTRB(
      xs.reduce(math.min) - 0.4,
      zs.reduce(math.min) - 0.4,
      xs.reduce(math.max) + 0.4,
      zs.reduce(math.max) + 0.4,
    );
  }

  @override
  bool shouldRepaint(covariant _RoomPainter old) => true;
}
