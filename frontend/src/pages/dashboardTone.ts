// When a dashboard health tile turns orange (warning) or red (danger); docs/2026-11-24-dashboard-design.md

export type Tone = "ok" | "warning" | "danger";

const LLM_WARNING_SHARE = 0.8;
const ERROR_MIN_CALLS = 10;
const ERROR_WARNING_SHARE = 0.1;
const ERROR_DANGER_SHARE = 0.25;
const QUEUE_WARNING_S = 5 * 60;
const QUEUE_DANGER_S = 15 * 60;

// Today's LLM calls against the new-trip ceiling, the lower of the two
export function llmTone(calls: number, ceiling: number): Tone {
  if (calls >= ceiling) return "danger";
  return calls >= ceiling * LLM_WARNING_SHARE ? "warning" : "ok";
}

// Share of failed LLM calls in the last hour; too few calls stay ok so one stray error is not red
export function errorTone(errors: number, calls: number): Tone {
  if (calls < ERROR_MIN_CALLS) return "ok";
  const share = errors / calls;
  if (share > ERROR_DANGER_SHARE) return "danger";
  return share > ERROR_WARNING_SHARE ? "warning" : "ok";
}

// Age in seconds of the oldest waiting job
export function queueTone(oldestQueuedS: number | null): Tone {
  if (oldestQueuedS === null) return "ok";
  if (oldestQueuedS > QUEUE_DANGER_S) return "danger";
  return oldestQueuedS > QUEUE_WARNING_S ? "warning" : "ok";
}

// Any blocked provider refuses work
export function blockTone(blocks: number): Tone {
  return blocks > 0 ? "danger" : "ok";
}
