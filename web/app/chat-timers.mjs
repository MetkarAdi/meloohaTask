/** Start the three waiting stages for one assistant response. */
export function startTypingWaitTimers(onStage, onTimeout, timers = globalThis) {
  const waking = timers.setTimeout(() => onStage('waking'), 8_000);
  const waiting = timers.setTimeout(() => onStage('waiting'), 25_000);
  const timeout = timers.setTimeout(onTimeout, 60_000);
  return () => {
    timers.clearTimeout(waking);
    timers.clearTimeout(waiting);
    timers.clearTimeout(timeout);
  };
}
