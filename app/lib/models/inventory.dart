class PriceQuote {
  PriceQuote({
    this.amount = 0,
    this.low = 0,
    this.high = 0,
    this.source = '',
    this.url = '',
    this.retrievedAt = '',
    this.converted = false,
    this.conditionAssumed = '',
    this.currency = '',
  });

  double amount;
  double low;
  double high;
  String source;
  String url;
  String retrievedAt;
  bool converted;
  String conditionAssumed;
  String currency;

  bool get hasAmount => amount > 0 || low > 0 || high > 0;
  bool get hasSource => source.isNotEmpty || url.isNotEmpty;

  void merge(Map<String, dynamic>? m) {
    if (m == null || m.isEmpty) return;
    if (m['amount'] is num) amount = (m['amount'] as num).toDouble();
    if (m['low'] is num) low = (m['low'] as num).toDouble();
    if (m['high'] is num) high = (m['high'] as num).toDouble();
    if (m['source'] is String) source = m['source'] as String;
    if (m['url'] is String) url = m['url'] as String;
    if (m['retrieved_at'] is String) retrievedAt = m['retrieved_at'] as String;
    if (m['converted'] == true) converted = true;
    if (m['condition_assumed'] is String) {
      conditionAssumed = m['condition_assumed'] as String;
    }
    if (m['currency'] is String) currency = m['currency'] as String;
  }

  static PriceQuote fromMap(Map<String, dynamic>? m) {
    final q = PriceQuote();
    q.merge(m);
    return q;
  }
}

class InvBook {
  InvBook({
    required this.id,
    this.title = '',
    this.author = '',
    this.edition = '',
    this.isbn = '',
    this.status = 'logging',
    this.idConfidence = 0,
    this.spineHeightCm = 0,
    this.spineThicknessCm = 0,
    this.scaleMethod = '',
    this.shelf = '',
    this.imageUrl = '',
    this.priceLabel = '',
    this.currency = '',
    this.processing = true,
    PriceQuote? replacementCost,
    PriceQuote? usedValue,
    this.mapX,
    this.mapZ,
  })  : replacementCost = replacementCost ?? PriceQuote(),
        usedValue = usedValue ?? PriceQuote();

  final String id;
  String title;
  String author;
  String edition;
  String isbn;
  String status;
  double idConfidence;
  double spineHeightCm;
  double spineThicknessCm;
  String scaleMethod;
  String shelf;
  String imageUrl;
  String priceLabel;
  String currency;
  bool processing;
  PriceQuote replacementCost;
  PriceQuote usedValue;
  double? mapX;
  double? mapZ;

  String get displayTitle =>
      title.trim().isEmpty ? '(unreadable spine)' : title;

  void merge(Map<String, dynamic> m) {
    if (m['title'] is String && (m['title'] as String).isNotEmpty) {
      title = m['title'] as String;
    }
    if (m['author'] is String) author = m['author'] as String;
    if (m['edition'] is String) edition = m['edition'] as String;
    if (m['isbn'] is String) isbn = m['isbn'] as String;
    if (m['status'] is String) status = m['status'] as String;
    if (m['id_confidence'] is num) {
      idConfidence = (m['id_confidence'] as num).toDouble();
    }
    if (m['spine_height_cm'] is num) {
      spineHeightCm = (m['spine_height_cm'] as num).toDouble();
    }
    if (m['spine_thickness_cm'] is num) {
      spineThicknessCm = (m['spine_thickness_cm'] as num).toDouble();
    }
    if (m['scale_method'] is String) scaleMethod = m['scale_method'] as String;
    if (m['shelf'] is String && (m['shelf'] as String).isNotEmpty) {
      shelf = m['shelf'] as String;
    }
    if (m['image_url'] is String && (m['image_url'] as String).isNotEmpty) {
      imageUrl = m['image_url'] as String;
    }
    if (m['price_label'] is String) priceLabel = m['price_label'] as String;
    if (m['currency'] is String) currency = m['currency'] as String;
    if (m.containsKey('processing')) processing = m['processing'] == true;
    if (m['replacement_cost'] is Map) {
      replacementCost.merge(Map<String, dynamic>.from(m['replacement_cost'] as Map));
    }
    if (m['used_value'] is Map) {
      usedValue.merge(Map<String, dynamic>.from(m['used_value'] as Map));
    }
  }

  static InvBook fromMap(Map<String, dynamic> m) {
    final b = InvBook(id: m['id'] as String);
    b.merge(m);
    return b;
  }
}

class InvItem {
  InvItem({
    required this.id,
    this.category = 'other',
    this.description = '',
    this.brandModel = '',
    this.status = 'logging',
    this.appraisalReason = '',
    this.imageUrl = '',
    this.priceLabel = '',
    this.processing = true,
    PriceQuote? replacementCost,
    this.mapX,
    this.mapZ,
  }) : replacementCost = replacementCost ?? PriceQuote();

  final String id;
  String category;
  String description;
  String brandModel;
  String status;
  String appraisalReason;
  String imageUrl;
  String priceLabel;
  bool processing;
  PriceQuote replacementCost;
  double? mapX;
  double? mapZ;

  String get displayTitle =>
      description.trim().isEmpty ? category : description;

  void merge(Map<String, dynamic> m) {
    if (m['category'] is String) category = m['category'] as String;
    if (m['description'] is String) description = m['description'] as String;
    if (m['brand_model'] is String) brandModel = m['brand_model'] as String;
    if (m['status'] is String) status = m['status'] as String;
    if (m['appraisal_reason'] is String) {
      appraisalReason = m['appraisal_reason'] as String;
    }
    if (m['image_url'] is String && (m['image_url'] as String).isNotEmpty) {
      imageUrl = m['image_url'] as String;
    }
    if (m['price_label'] is String) priceLabel = m['price_label'] as String;
    if (m.containsKey('processing')) processing = m['processing'] == true;
    if (m['replacement_cost'] is Map) {
      replacementCost.merge(Map<String, dynamic>.from(m['replacement_cost'] as Map));
    }
  }

  static InvItem fromMap(Map<String, dynamic> m) {
    final i = InvItem(id: m['id'] as String);
    i.merge(m);
    return i;
  }
}

class RoomPlaneMark {
  RoomPlaneMark({
    required this.id,
    required this.kind,
    required this.cx,
    required this.cz,
    required this.widthM,
    required this.depthM,
    required this.areaM2,
  });

  final String id;
  final String kind; // floor | wall
  final double cx;
  final double cz;
  final double widthM;
  final double depthM;
  final double areaM2;
}

class RoomStats {
  double lengthM = 0;
  double widthM = 0;
  double heightM = 0;
  double floorAreaM2 = 0;
  double wallAreaM2 = 0;
  String scaleMethod = '';
}
