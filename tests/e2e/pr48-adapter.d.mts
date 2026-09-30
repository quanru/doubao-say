export const PR48_PIN: Readonly<{ before: string; after: string }>;
export interface Pr48Adapter {
  prepare(input: { variant: 'before' | 'after' }): Promise<void>;
  observe(input: { variant: 'before' | 'after'; phase: 'ready' | 'start_failed' | 'listening' | 'finished' }): Promise<void>;
  control(input: { variant: 'before' | 'after'; action: 'start' | 'finish' }): Promise<void>;
  cleanup(): Promise<void>;
}
export function assertPr48Profile(env: NodeJS.ProcessEnv): void;
export function validatePr48Status(value: unknown, variant: string, phase: string): boolean;
export function createPr48Adapter(options: {
  guest: (command: string, timeoutMs?: number) => string;
  env: NodeJS.ProcessEnv;
  record?: (event: { at: string; type: string; [key: string]: unknown }) => void;
}): Pr48Adapter;
