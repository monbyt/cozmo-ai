import 'package:cozmo_sweep/screens/ar_guidance_screen.dart';
import 'package:flutter/material.dart';

/// Live backend for reviewers — baked in so they only tap Start sweep.
const kBackendWsBase = 'wss://cozmo-claim-agent.fly.dev';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const CozmoApp());
}

class CozmoApp extends StatelessWidget {
  const CozmoApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Cozmo Sweep',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF7C8CFF),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  String _country = 'US';
  String _currency = 'USD';

  static const _countries = {
    'US': 'USD',
    'GB': 'GBP',
    'DE': 'EUR',
    'AE': 'AED',
    'TR': 'TRY',
  };

  void _start() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ArGuidanceScreen(
          backendWsBase: kBackendWsBase,
          country: _country,
          currency: _currency,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 16),
              Text(
                'Cozmo Sweep',
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(height: 8),
              Text(
                'One continuous camera sweep. The agent logs books and items as you walk.',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Colors.white70,
                    ),
              ),
              const SizedBox(height: 24),
              DropdownButtonFormField<String>(
                initialValue: _country,
                decoration: const InputDecoration(
                  labelText: 'Country / currency',
                  border: OutlineInputBorder(),
                ),
                items: _countries.entries
                    .map(
                      (e) => DropdownMenuItem(
                        value: e.key,
                        child: Text('${e.key} · ${e.value}'),
                      ),
                    )
                    .toList(),
                onChanged: (v) {
                  if (v == null) return;
                  setState(() {
                    _country = v;
                    _currency = _countries[v]!;
                  });
                },
              ),
              const Spacer(),
              FilledButton(
                onPressed: _start,
                child: const Padding(
                  padding: EdgeInsets.symmetric(vertical: 14),
                  child: Text('Start sweep'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
