import { useSyncExternalStore } from "react";
export type CandidatePreview = { url: string; name: string } | null;
let current: CandidatePreview = null;
const listeners = new Set<() => void>();
export function setCandidatePreview(value: CandidatePreview) {
  current = value;
  for (const callback of listeners) callback();
}
export function useCandidatePreview() {
  return useSyncExternalStore(
    (callback) => {
      listeners.add(callback);
      return () => {
        listeners.delete(callback);
      };
    },
    () => current,
  );
}
