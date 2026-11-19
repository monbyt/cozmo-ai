import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:audio_session/audio_session.dart';
import 'package:flutter_pcm_sound/flutter_pcm_sound.dart';
import 'package:record/record.dart' hide IosAudioCategory;

/// Mic PCM16@16kHz uplink + PCM16@24kHz playback (Gemini Live audio).
class VoiceIo {
  final _recorder = AudioRecorder();
  StreamSubscription<Uint8List>? _micSub;
  bool _playing = false;
  static const int _outRate = 24000;

  Future<void> _routeToSpeaker() async {
    final session = await AudioSession.instance;
    await session.configure(AudioSessionConfiguration(
      avAudioSessionCategory: AVAudioSessionCategory.playAndRecord,
      avAudioSessionCategoryOptions:
          AVAudioSessionCategoryOptions.defaultToSpeaker |
          AVAudioSessionCategoryOptions.allowBluetooth |
          AVAudioSessionCategoryOptions.mixWithOthers,
      avAudioSessionMode: AVAudioSessionMode.voiceChat,
      avAudioSessionSetActiveOptions: AVAudioSessionSetActiveOptions.none,
      androidAudioAttributes: const AndroidAudioAttributes(
        contentType: AndroidAudioContentType.speech,
        usage: AndroidAudioUsage.voiceCommunication,
      ),
      androidAudioFocusGainType: AndroidAudioFocusGainType.gain,
    ));
    await session.setActive(true);
  }

  Future<void> start({required void Function(Uint8List pcm16) onMicPcm}) async {
    if (!await _recorder.hasPermission()) {
      throw StateError('Microphone permission denied');
    }

    await FlutterPcmSound.setup(
      sampleRate: 24000,
      channelCount: 1,
      iosAudioCategory: IosAudioCategory.playAndRecord,
    );
    await _routeToSpeaker();
    await FlutterPcmSound.setFeedThreshold(1200);
    FlutterPcmSound.setFeedCallback((_) {});
    FlutterPcmSound.start();
    _playing = true;

    final stream = await _recorder.startStream(const RecordConfig(
      encoder: AudioEncoder.pcm16bits,
      sampleRate: 16000,
      numChannels: 1,
      autoGain: true,
      echoCancel: true,
      noiseSuppress: true,
    ));
    _micSub = stream.listen(onMicPcm);
  }

  void playPcm24Base64(String base64) {
    if (!_playing) return;
    final bytes = base64Decode(base64);
    final even = bytes.length & 1 == 0 ? bytes.length : bytes.length - 1;
    if (even <= 0) return;
    FlutterPcmSound.feed(
      PcmArrayInt16(bytes: ByteData.sublistView(bytes, 0, even)),
    );
  }

  /// Soft barge-in: drop queued playback without tearing down the audio unit.
  Future<void> stopPlayback() async {
    // flutter_pcm_sound has no clear(); release/setup is too slow for Live interrupts.
    // Feeding a tiny silence nudge keeps the unit alive while the agent restarts.
    try {
      FlutterPcmSound.feed(PcmArrayInt16.zeros(count: 240)); // 10ms @ 24kHz
    } catch (_) {}
  }

  /// Soft two-note log chime (replaces spoken "got it").
  void playLogChime() {
    if (!_playing) return;
    try {
      FlutterPcmSound.feed(PcmArrayInt16(bytes: _chimePcm()));
    } catch (_) {}
  }

  ByteData _chimePcm() {
    // A5 → C#6, short decaying sine — calm confirmation ding.
    const freqs = [880.0, 1108.73];
    const noteMs = 90;
    const gapMs = 30;
    final noteSamples = (_outRate * noteMs / 1000).round();
    final gapSamples = (_outRate * gapMs / 1000).round();
    final total = noteSamples * 2 + gapSamples;
    final bd = ByteData(total * 2);
    var o = 0;
    for (var n = 0; n < freqs.length; n++) {
      final f = freqs[n];
      for (var i = 0; i < noteSamples; i++) {
        final t = i / _outRate;
        final env = math.sin(math.pi * i / noteSamples); // fade in/out
        final sample = (0.22 * env * math.sin(2 * math.pi * f * t) * 32767)
            .round()
            .clamp(-32767, 32767);
        bd.setInt16(o * 2, sample, Endian.little);
        o++;
      }
      if (n == 0) {
        for (var i = 0; i < gapSamples; i++) {
          bd.setInt16(o * 2, 0, Endian.little);
          o++;
        }
      }
    }
    return bd;
  }

  Future<void> stop() async {
    await _micSub?.cancel();
    _micSub = null;
    try {
      await _recorder.stop();
    } catch (_) {}
    _playing = false;
    try {
      await FlutterPcmSound.release();
    } catch (_) {}
  }

  Future<void> dispose() async {
    await stop();
    await _recorder.dispose();
  }
}
