import 'package:flutter/material.dart';

Future<void> showSweepSummarySheet(
  BuildContext context,
  Map<String, dynamic> summary, {
  String? jsonUrl,
  String? htmlUrl,
}) {
  final room = (summary['room'] as Map?)?.cast<String, dynamic>() ?? {};
  final books = (summary['books_preview'] as List?) ?? const [];
  final items = (summary['items_preview'] as List?) ?? const [];

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
          child: SingleChildScrollView(
            child: Column(
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
                  'Claim summary',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  (summary['speak'] as String?) ?? '',
                  style: const TextStyle(color: Colors.white60, fontSize: 13),
                ),
                const SizedBox(height: 16),
                const Text(
                  'Books',
                  style: TextStyle(
                      color: Colors.white, fontWeight: FontWeight.w700),
                ),
                _kv('Count', '${summary['book_count'] ?? 0}'),
                _kv('Identified', '${summary['books_identified'] ?? 0}'),
                _kv('Unidentified', '${summary['books_unidentified'] ?? 0}'),
                _kv('Shelf run', '${summary['shelf_run_m'] ?? 0} m'),
                _kv('Replacement total',
                    '${summary['books_replacement_cost'] ?? 0}'),
                _kv('Used total', '${summary['books_used_value'] ?? 0}'),
                const SizedBox(height: 12),
                const Text(
                  'Non-book items',
                  style: TextStyle(
                      color: Colors.white, fontWeight: FontWeight.w700),
                ),
                _kv('Count', '${summary['item_count'] ?? 0}'),
                _kv(
                  'Replacement range',
                  '${summary['items_replacement_cost_low'] ?? 0}'
                      '–${summary['items_replacement_cost_high'] ?? 0}',
                ),
                const SizedBox(height: 12),
                const Text(
                  'Room',
                  style: TextStyle(
                      color: Colors.white, fontWeight: FontWeight.w700),
                ),
                _kv(
                  'Size',
                  room['length_m'] != null && (room['length_m'] as num) > 0
                      ? '${room['length_m']} × ${room['width_m']} × ${room['height_m']} m'
                      : '—',
                ),
                _kv(
                  'Floor',
                  room['floor_area_m2'] != null &&
                          (room['floor_area_m2'] as num) > 0
                      ? '${room['floor_area_m2']} m² (${room['floor_area_ft2']} ft²)'
                      : '—',
                ),
                _kv('Walls', '${room['wall_area_m2'] ?? 0} m²'),
                _kv('Shelved wall', '${room['shelved_wall_area_m2'] ?? 0} m²'),
                _kv('Scale', '${room['scale_method'] ?? '—'}'),
                const SizedBox(height: 12),
                _kv('Review queue',
                    '${summary['review_queue_count'] ?? 0} lines'),
                _kv('Excluded from totals',
                    '${summary['excluded_from_totals'] ?? 0}'),
                if (books.isNotEmpty) ...[
                  const SizedBox(height: 14),
                  const Text('Sample books',
                      style: TextStyle(
                          color: Colors.white70, fontWeight: FontWeight.w600)),
                  ...books.take(8).map((b) {
                    final m = Map<String, dynamic>.from(b as Map);
                    return Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        '• ${m['title']} (${m['status']})'
                        '${m['replacement'] != null ? ' · ${m['replacement']}' : ''}',
                        style: const TextStyle(
                            color: Colors.white54, fontSize: 12),
                      ),
                    );
                  }),
                ],
                if (items.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  const Text('Sample items',
                      style: TextStyle(
                          color: Colors.white70, fontWeight: FontWeight.w600)),
                  ...items.take(6).map((i) {
                    final m = Map<String, dynamic>.from(i as Map);
                    return Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        '• ${m['description']} (${m['category']})',
                        style: const TextStyle(
                            color: Colors.white54, fontSize: 12),
                      ),
                    );
                  }),
                ],
                if (jsonUrl != null || htmlUrl != null) ...[
                  const SizedBox(height: 16),
                  Text(
                    [
                      if (jsonUrl != null) 'JSON: $jsonUrl',
                      if (htmlUrl != null) 'Report: $htmlUrl',
                    ].join('\n'),
                    style: const TextStyle(color: Colors.white38, fontSize: 11),
                  ),
                ],
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: () => Navigator.pop(ctx),
                  child: const Text('Done'),
                ),
              ],
            ),
          ),
        ),
      );
    },
  );
}

Widget _kv(String k, String v) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          SizedBox(
            width: 140,
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
