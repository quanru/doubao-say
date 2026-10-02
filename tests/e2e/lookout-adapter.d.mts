export interface LookoutStatus {
  phase: 'working' | 'idle' | 'due' | 'break' | 'paused';
  remainingSec: number;
  lastBreakAt: string | null;
}
export interface LookoutAdapter {
  prepare(input: { allowSkip: boolean; breakSec: 1800 }): Promise<void>;
  assertPhase(input: { phase: 'working' | 'break'; overlay: boolean }): Promise<LookoutStatus>;
  assertAllowSkip(input: { value: boolean }): Promise<void>;
  assertSkipped(): void;
  endForCleanup(): Promise<void>;
  cleanup(): Promise<void>;
}
export const PIN: Readonly<{ repository: string; sha: string; id: string }>;
export function assertLookoutProfile(env: NodeJS.ProcessEnv): void;
export function createLookoutAdapter(options: {
  guest: (command: string, timeoutMs?: number) => string;
  env: NodeJS.ProcessEnv;
  record?: (event: { at: string; type: string; [key: string]: unknown }) => void;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}): LookoutAdapter;
export function prepareLookoutCase(options: {
  context: { lookoutCase?: { runId: string; adapter: LookoutAdapter } };
  runId: string;
  onTeardown: (cleanup: () => Promise<void>) => void;
  adapter: LookoutAdapter;
  input: { allowSkip: boolean; breakSec: 1800 };
}): Promise<void>;
