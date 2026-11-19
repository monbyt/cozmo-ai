import 'dart:typed_data';

import 'package:image/image.dart' as img;

/// Downscale ARKit capture → compact JPEG for Gemini Live.
/// Kept small/fast so walking capture can outrun background ID/pricing.
Uint8List? toLiveJpeg(
  Uint8List pngOrJpeg, {
  int maxWidth = 480,
  int quality = 55,
}) {
  if (pngOrJpeg.isEmpty) return null;
  try {
    final decoded = img.decodeImage(pngOrJpeg);
    if (decoded == null) return null;
    final resized = decoded.width > maxWidth
        ? img.copyResize(
            decoded,
            width: maxWidth,
            interpolation: img.Interpolation.average,
          )
        : decoded;
    return Uint8List.fromList(img.encodeJpg(resized, quality: quality));
  } catch (_) {
    return null;
  }
}

/// Isolate entrypoint — encode without blocking the AR/UI isolate.
Uint8List? encodeLiveJpegIsolate(Uint8List bytes) => toLiveJpeg(bytes);
