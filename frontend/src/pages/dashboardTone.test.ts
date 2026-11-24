import { describe, expect, it } from "vitest";
import { blockTone, errorTone, llmTone, queueTone } from "./dashboardTone.ts";

describe("dashboardTone", () => {
  it("llm_tone_turns_warning_at_80_percent_and_danger_at_the_ceiling", () => {
    expect([llmTone(639, 800), llmTone(640, 800), llmTone(800, 800)]).toEqual(["ok", "warning", "danger"]);
  });

  it("error_tone_needs_10_calls_and_is_strictly_above_the_thresholds", () => {
    expect([errorTone(5, 9), errorTone(1, 10), errorTone(2, 10), errorTone(25, 100), errorTone(26, 100)]).toEqual([
      "ok",
      "ok",
      "warning",
      "warning",
      "danger",
    ]);
  });

  it("queue_tone_turns_warning_after_5_minutes_and_danger_after_15", () => {
    expect([queueTone(null), queueTone(300), queueTone(301), queueTone(900), queueTone(901)]).toEqual([
      "ok",
      "ok",
      "warning",
      "warning",
      "danger",
    ]);
  });

  it("block_tone_is_danger_with_any_block", () => {
    expect([blockTone(0), blockTone(1)]).toEqual(["ok", "danger"]);
  });
});
