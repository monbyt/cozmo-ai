import 'package:cozmo_sweep/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('Home shows AR entry point', (tester) async {
    await tester.pumpWidget(const CozmoApp());
    expect(find.text('Start AR guidance'), findsOneWidget);
  });
}
