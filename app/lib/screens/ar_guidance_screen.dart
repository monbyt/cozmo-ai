import 'dart:math' as math;

import 'package:arkit_plugin/arkit_plugin.dart';
import 'package:collection/collection.dart';
import 'package:flutter/material.dart';
import 'package:vector_math/vector_math_64.dart' as vector;

enum PinKind { next, revisit }

class ArGuidanceScreen extends StatefulWidget {
  const ArGuidanceScreen({super.key});

  @override
  State<ArGuidanceScreen> createState() => _ArGuidanceScreenState();
}

class _ArGuidanceScreenState extends State<ArGuidanceScreen> {
  ARKitController? _controller;
  final Map<String, _TrackedPlane> _planes = {};
  final List<_PlacedPin> _pins = [];
  PinKind _mode = PinKind.next;
  String _status = 'Move slowly — finding floor & walls…';

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        children: [
          ARKitSceneView(
            configuration: ARKitConfiguration.worldTracking,
            planeDetection: ARPlaneDetection.horizontalAndVertical,
            showFeaturePoints: true,
            enableTapRecognizer: true,
            autoenablesDefaultLighting: true,
            onARKitViewCreated: _onViewCreated,
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
              child: Column(
                children: [
                  Row(
                    children: [
                      IconButton.filledTonal(
                        onPressed: () => Navigator.of(context).maybePop(),
                        icon: const Icon(Icons.arrow_back),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 10,
                          ),
                          decoration: BoxDecoration(
                            color: Colors.black.withValues(alpha: 0.55),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Text(
                            _status,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const Spacer(),
                  _ModeBar(
                    mode: _mode,
                    planeCount: _planes.length,
                    pinCount: _pins.length,
                    onMode: (m) => setState(() => _mode = m),
                    onClearPins: _clearPins,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _onViewCreated(ARKitController controller) {
    _controller = controller;
    controller.addCoachingOverlay(CoachingOverlayGoal.horizontalPlane);
    controller.onAddNodeForAnchor = _onAddAnchor;
    controller.onUpdateNodeForAnchor = _onUpdateAnchor;
    controller.onARTap = _onArTap;
    setState(() => _status = 'Scan the room — tap a plane to drop a pin');
  }

  void _onAddAnchor(ARKitAnchor anchor) {
    if (anchor is! ARKitPlaneAnchor) return;
    final plane = ARKitPlane(
      width: anchor.extent.x,
      height: anchor.extent.z,
      materials: [
        ARKitMaterial(
          transparency: 0.35,
          diffuse: ARKitMaterialProperty.color(
            anchor.extent.y.abs() < 0.05
                ? const Color(0xFF7C8CFF)
                : const Color(0xFF3BBD6B),
          ),
        ),
      ],
    );
    final node = ARKitNode(
      geometry: plane,
      position: vector.Vector3(anchor.center.x, 0, anchor.center.z),
      rotation: vector.Vector4(1, 0, 0, -math.pi / 2),
    );
    _controller?.add(node, parentNodeName: anchor.nodeName);
    _planes[anchor.identifier] = _TrackedPlane(anchor: anchor, node: node, plane: plane);
    setState(() {
      _status = '${_planes.length} plane(s) · tap to place ${_mode.label}';
    });
  }

  void _onUpdateAnchor(ARKitAnchor anchor) {
    if (anchor is! ARKitPlaneAnchor) return;
    final tracked = _planes[anchor.identifier];
    if (tracked == null) return;
    tracked.anchor = anchor;
    tracked.node.position = vector.Vector3(anchor.center.x, 0, anchor.center.z);
    tracked.plane.width.value = anchor.extent.x;
    tracked.plane.height.value = anchor.extent.z;
  }

  void _onArTap(List<ARKitTestResult> results) {
    final hit = results.firstWhereOrNull(
          (r) => r.type == ARKitHitTestResultType.existingPlaneUsingExtent,
        ) ??
        results.firstWhereOrNull(
          (r) => r.type == ARKitHitTestResultType.featurePoint,
        );
    if (hit == null) {
      setState(() => _status = 'No surface hit — pan until planes show, then tap');
      return;
    }
    final position = vector.Vector3(
      hit.worldTransform.getColumn(3).x,
      hit.worldTransform.getColumn(3).y,
      hit.worldTransform.getColumn(3).z,
    );
    _placePin(position, _mode);
  }

  void _placePin(vector.Vector3 position, PinKind kind) {
    final controller = _controller;
    if (controller == null) return;

    final color = kind == PinKind.next
        ? const Color(0xFF7C8CFF)
        : const Color(0xFFE8A538);

    final stem = ARKitNode(
      geometry: ARKitCylinder(
        radius: 0.01,
        height: 0.28,
        materials: [
          ARKitMaterial(
            lightingModelName: ARKitLightingModel.constant,
            diffuse: ARKitMaterialProperty.color(color),
          ),
        ],
      ),
      position: vector.Vector3(position.x, position.y + 0.14, position.z),
    );
    controller.add(stem);

    final head = ARKitNode(
      geometry: ARKitSphere(
        radius: 0.045,
        materials: [
          ARKitMaterial(
            lightingModelName: ARKitLightingModel.constant,
            diffuse: ARKitMaterialProperty.color(color),
          ),
        ],
      ),
      position: vector.Vector3(position.x, position.y + 0.32, position.z),
    );
    controller.add(head);

    final label = ARKitNode(
      geometry: ARKitText(
        text: kind.label,
        extrusionDepth: 0.4,
        materials: [
          ARKitMaterial(diffuse: ARKitMaterialProperty.color(Colors.white)),
        ],
      ),
      position: vector.Vector3(position.x - 0.06, position.y + 0.40, position.z),
      scale: vector.Vector3.all(0.0025),
    );
    controller.add(label);

    _pins.add(_PlacedPin(kind: kind, stem: stem, head: head, label: label));
    setState(() {
      _status =
          '${kind.label} pin dropped · ${_pins.length} pin(s) · ${_planes.length} plane(s)';
    });
  }

  Future<void> _clearPins() async {
    final controller = _controller;
    if (controller == null) return;
    for (final pin in _pins) {
      await controller.remove(pin.stem.name);
      await controller.remove(pin.head.name);
      await controller.remove(pin.label.name);
    }
    _pins.clear();
    setState(() => _status = 'Pins cleared · ${_planes.length} plane(s)');
  }
}

class _TrackedPlane {
  _TrackedPlane({
    required this.anchor,
    required this.node,
    required this.plane,
  });

  ARKitPlaneAnchor anchor;
  final ARKitNode node;
  final ARKitPlane plane;
}

class _PlacedPin {
  _PlacedPin({
    required this.kind,
    required this.stem,
    required this.head,
    required this.label,
  });

  final PinKind kind;
  final ARKitNode stem;
  final ARKitNode head;
  final ARKitNode label;
}

extension on PinKind {
  String get label => this == PinKind.next ? 'NEXT' : 'REVISIT';
}

class _ModeBar extends StatelessWidget {
  const _ModeBar({
    required this.mode,
    required this.planeCount,
    required this.pinCount,
    required this.onMode,
    required this.onClearPins,
  });

  final PinKind mode;
  final int planeCount;
  final int pinCount;
  final ValueChanged<PinKind> onMode;
  final VoidCallback onClearPins;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            '$planeCount planes · $pinCount pins',
            style: const TextStyle(color: Colors.white60, fontSize: 12),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: _ChipButton(
                  selected: mode == PinKind.next,
                  color: const Color(0xFF7C8CFF),
                  label: 'Next',
                  onTap: () => onMode(PinKind.next),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _ChipButton(
                  selected: mode == PinKind.revisit,
                  color: const Color(0xFFE8A538),
                  label: 'Revisit',
                  onTap: () => onMode(PinKind.revisit),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filledTonal(
                onPressed: onClearPins,
                tooltip: 'Clear pins',
                icon: const Icon(Icons.delete_outline),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'Tap a detected plane to drop the selected pin.',
            style: TextStyle(color: Colors.white54, fontSize: 11),
          ),
        ],
      ),
    );
  }
}

class _ChipButton extends StatelessWidget {
  const _ChipButton({
    required this.selected,
    required this.color,
    required this.label,
    required this.onTap,
  });

  final bool selected;
  final Color color;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? color : Colors.white10,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontWeight: FontWeight.w700,
              color: selected ? Colors.black : Colors.white,
            ),
          ),
        ),
      ),
    );
  }
}
