export type TypingStage = 'waking' | 'waiting';
export function startTypingWaitTimers(
  onStage: (stage: TypingStage) => void,
  onTimeout: () => void,
  timers?: Pick<typeof globalThis, 'setTimeout' | 'clearTimeout'>,
): () => void;
