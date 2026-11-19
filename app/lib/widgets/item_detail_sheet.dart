import 'package:cozmo_sweep/models/inventory.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

Future<void> showInventoryDetail(BuildContext context, Object entry) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: const Color(0xFF12141A),
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
    ),
    builder: (_) {
      if (entry is InvBook) return _BookSheet(book: entry);
      if (entry is InvItem) return _ItemSheet(item: entry);
      return const SizedBox.shrink();
    },
  );
}

class _BookSheet extends StatelessWidget {
  const _BookSheet({required this.book});
  final InvBook book;

  @override
  Widget build(BuildContext context) {
    final rc = book.replacementCost;
    final uv = book.usedValue;
    return _SheetScaffold(
      title: book.displayTitle,
      imageUrl: book.imageUrl,
      rows: [
        _row('Kind', 'Book (spine)'),
        _row('Status', book.processing ? 'pricing in background…' : book.status),
        _row('Author', book.author.isEmpty ? '—' : book.author),
        _row('Edition', book.edition.isEmpty ? '—' : book.edition),
        _row('ISBN', book.isbn.isEmpty ? '—' : book.isbn),
        _row('Shelf', book.shelf.isEmpty ? '—' : book.shelf),
        _row(
          'Spine size',
          book.spineHeightCm > 0
              ? '${book.spineHeightCm.toStringAsFixed(1)} × '
                  '${book.spineThicknessCm.toStringAsFixed(1)} cm'
              : '—',
        ),
        _row('Scale', book.scaleMethod.isEmpty ? '—' : book.scaleMethod),
        _row(
          'ID confidence',
          book.idConfidence > 0
              ? '${(book.idConfidence * 100).round()}%'
              : '—',
        ),
        _row(
          'Replacement',
          book.processing
              ? 'looking up…'
              : (rc.hasAmount
                  ? '${rc.currency} ${rc.amount.toStringAsFixed(2)}'
                      '${rc.converted ? ' (converted)' : ''}'
                  : (book.priceLabel.isEmpty ? 'no sourced price' : book.priceLabel)),
        ),
        if (rc.hasSource) _row('New source', '${rc.source}${rc.url.isNotEmpty ? '\n${rc.url}' : ''}'),
        if (rc.retrievedAt.isNotEmpty) _row('Retrieved', rc.retrievedAt),
        _row(
          'Used value',
          uv.hasAmount
              ? '${uv.currency} ${uv.amount.toStringAsFixed(2)}'
                  '${uv.conditionAssumed.isNotEmpty ? ' · ${uv.conditionAssumed}' : ''}'
              : '—',
        ),
        if (uv.hasSource) _row('Used source', '${uv.source}${uv.url.isNotEmpty ? '\n${uv.url}' : ''}'),
      ],
      note: book.status == 'needs_appraisal'
          ? 'Flagged for human appraisal — not auto-priced.'
          : book.status == 'unidentified'
              ? 'Spine unread — logged with dimensions only, no guessed title.'
              : null,
      copyUrls: [
        if (rc.url.isNotEmpty) rc.url,
        if (uv.url.isNotEmpty) uv.url,
      ],
    );
  }
}

class _ItemSheet extends StatelessWidget {
  const _ItemSheet({required this.item});
  final InvItem item;

  @override
  Widget build(BuildContext context) {
    final rc = item.replacementCost;
    final range = rc.low > 0 && rc.high > 0 && rc.low != rc.high
        ? '${rc.low.toStringAsFixed(0)}–${rc.high.toStringAsFixed(0)}'
        : (rc.low > 0
            ? rc.low.toStringAsFixed(2)
            : (rc.amount > 0 ? rc.amount.toStringAsFixed(2) : ''));
    return _SheetScaffold(
      title: item.displayTitle,
      imageUrl: item.imageUrl,
      rows: [
        _row('Kind', 'Non-book item'),
        _row('Category', item.category),
        _row('Status', item.processing ? 'pricing in background…' : item.status),
        _row('Brand / model', item.brandModel.isEmpty ? '—' : item.brandModel),
        _row(
          'Replacement',
          item.processing
              ? 'looking up…'
              : (range.isNotEmpty
                  ? range
                  : (item.priceLabel.isEmpty ? 'no sourced price' : item.priceLabel)),
        ),
        if (rc.hasSource) _row('Source', '${rc.source}${rc.url.isNotEmpty ? '\n${rc.url}' : ''}'),
        if (rc.retrievedAt.isNotEmpty) _row('Retrieved', rc.retrievedAt),
        if (item.appraisalReason.isNotEmpty)
          _row('Appraisal reason', item.appraisalReason),
      ],
      note: item.status == 'needs_appraisal'
          ? 'Art/portrait defaults to needs appraisal unless marked as a print.'
          : null,
      copyUrls: [if (rc.url.isNotEmpty) rc.url],
    );
  }
}

Widget _row(String k, String v) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 120,
            child: Text(
              k,
              style: const TextStyle(color: Colors.white54, fontSize: 13),
            ),
          ),
          Expanded(
            child: Text(
              v,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );

class _SheetScaffold extends StatelessWidget {
  const _SheetScaffold({
    required this.title,
    required this.rows,
    this.imageUrl = '',
    this.note,
    this.copyUrls = const [],
  });

  final String title;
  final List<Widget> rows;
  final String imageUrl;
  final String? note;
  final List<String> copyUrls;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.only(
          left: 20,
          right: 20,
          top: 12,
          bottom: 24 + MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: SingleChildScrollView(
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
              const SizedBox(height: 16),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (imageUrl.isNotEmpty)
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: Image.network(
                        imageUrl,
                        width: 64,
                        height: 88,
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => const SizedBox.shrink(),
                      ),
                    ),
                  if (imageUrl.isNotEmpty) const SizedBox(width: 14),
                  Expanded(
                    child: Text(
                      title,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              ...rows,
              if (note != null) ...[
                const SizedBox(height: 12),
                Text(
                  note!,
                  style: const TextStyle(color: Color(0xFFFFC107), fontSize: 12),
                ),
              ],
              if (copyUrls.isNotEmpty) ...[
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: () async {
                    await Clipboard.setData(ClipboardData(text: copyUrls.join('\n')));
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Source URL copied')),
                      );
                    }
                  },
                  icon: const Icon(Icons.link, size: 16),
                  label: const Text('Copy shopping source URL'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
