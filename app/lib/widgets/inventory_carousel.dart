import 'package:cozmo_sweep/models/inventory.dart';
import 'package:flutter/material.dart';

/// Newest-first combined log feed (latest capture on top).
class InventoryLogFeed extends StatelessWidget {
  const InventoryLogFeed({
    super.key,
    required this.entries,
    required this.onOpen,
  });

  final List<Object> entries;
  final void Function(Object entry) onOpen;

  @override
  Widget build(BuildContext context) {
    if (entries.isEmpty) {
      return Container(
        height: 120,
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: const Text(
          'Logged items appear here as they’re captured.',
          style: TextStyle(color: Colors.white70, fontSize: 13),
          textAlign: TextAlign.center,
        ),
      );
    }

    return SizedBox(
      height: 200,
      child: ListView.separated(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        itemCount: entries.length,
        separatorBuilder: (_, __) => const SizedBox(height: 8),
        itemBuilder: (context, i) {
          final entry = entries[i];
          final c = _cardFor(entry);
          if (c == null) return const SizedBox.shrink();
          final newest = i == 0;
          return GestureDetector(
            onTap: () => onOpen(c.entry),
            child: Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: newest
                    ? const Color(0xFF1B3D2F)
                    : const Color(0xFF16181F),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(
                  color: c.processing
                      ? const Color(0xFF7C8CFF)
                      : (newest
                          ? const Color(0xFF3DCF8E)
                          : Colors.white12),
                ),
              ),
              child: Row(
                children: [
                  _Cover(url: c.imageUrl, label: c.title, kind: c.kind),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          c.title,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w700,
                            fontSize: 13,
                          ),
                        ),
                        if (c.sub.isNotEmpty) ...[
                          const SizedBox(height: 4),
                          Text(
                            c.sub,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: Colors.white60,
                              fontSize: 11,
                            ),
                          ),
                        ],
                        const SizedBox(height: 6),
                        Text(
                          c.processing
                              ? 'pricing…'
                              : (c.price.isNotEmpty
                                  ? c.price
                                  : c.status.replaceAll('_', ' ')),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: c.processing
                                ? const Color(0xFF9AA8FF)
                                : (c.price.isNotEmpty
                                    ? const Color(0xFFB8F0C0)
                                    : Colors.white54),
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (newest)
                    const Padding(
                      padding: EdgeInsets.only(left: 6),
                      child: Text(
                        'NEW',
                        style: TextStyle(
                          color: Color(0xFF3DCF8E),
                          fontSize: 10,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 0.6,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  _CardData? _cardFor(Object entry) {
    if (entry is InvBook) {
      return _CardData(
        key: entry.id,
        entry: entry,
        title: entry.displayTitle,
        sub: entry.author,
        price: entry.priceLabel,
        status: entry.status,
        processing: entry.processing,
        imageUrl: entry.imageUrl,
        kind: 'book',
      );
    }
    if (entry is InvItem) {
      return _CardData(
        key: entry.id,
        entry: entry,
        title: entry.displayTitle,
        sub: [entry.category, entry.brandModel]
            .where((s) => s.isNotEmpty)
            .join(' · '),
        price: entry.priceLabel,
        status: entry.status,
        processing: entry.processing,
        imageUrl: entry.imageUrl,
        kind: 'item',
      );
    }
    return null;
  }
}

class _CardData {
  _CardData({
    required this.key,
    required this.entry,
    required this.title,
    required this.sub,
    required this.price,
    required this.status,
    required this.processing,
    required this.imageUrl,
    required this.kind,
  });

  final String key;
  final Object entry;
  final String title;
  final String sub;
  final String price;
  final String status;
  final bool processing;
  final String imageUrl;
  final String kind;
}

class _Cover extends StatelessWidget {
  const _Cover({required this.url, required this.label, required this.kind});

  final String url;
  final String label;
  final String kind;

  @override
  Widget build(BuildContext context) {
    final letter = label.isEmpty ? '?' : label[0].toUpperCase();
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: SizedBox(
        width: 52,
        height: 72,
        child: url.isNotEmpty
            ? Image.network(url, fit: BoxFit.cover, errorBuilder: (_, __, ___) {
                return _Fallback(letter: letter, kind: kind);
              })
            : _Fallback(letter: letter, kind: kind),
      ),
    );
  }
}

class _Fallback extends StatelessWidget {
  const _Fallback({required this.letter, required this.kind});
  final String letter;
  final String kind;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: kind == 'book' ? const Color(0xFF2A3148) : const Color(0xFF24352A),
      child: Center(
        child: Text(
          letter,
          style: const TextStyle(
            color: Colors.white70,
            fontWeight: FontWeight.w800,
            fontSize: 22,
          ),
        ),
      ),
    );
  }
}
