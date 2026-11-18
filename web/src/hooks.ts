import { useSyncExternalStore } from 'react';
import { getState, subscribe, type State } from './state';

export function useAppState<T>(selector: (s: State) => T): T {
  return useSyncExternalStore(subscribe, () => selector(getState()));
}
