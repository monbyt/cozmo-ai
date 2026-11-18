import { useAppState } from './hooks';
import { HomeScreen } from './components/HomeScreen';
import { SweepScreen } from './components/SweepScreen';
import { PacketScreen } from './components/PacketScreen';

export default function App() {
  const screen = useAppState((s) => s.screen);
  if (screen === 'sweep') return <SweepScreen />;
  if (screen === 'packet') return <PacketScreen />;
  return <HomeScreen />;
}
