import { describe, expect, it } from "vitest";
import type { ChatEvent } from "./api.types.ts";
import { parseSse } from "./parseSse.ts";

// A byte stream that hands out the given chunks one read at a time
function byteStreamOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

// A byte stream built from text chunks
function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return byteStreamOf(chunks.map((chunk) => encoder.encode(chunk)));
}

// Every event a stream produces
async function collect(body: ReadableStream<Uint8Array>): Promise<ChatEvent[]> {
  const events: ChatEvent[] = [];
  for await (const event of parseSse(body, new AbortController().signal)) events.push(event);
  return events;
}

describe("parseSse", () => {
  it("emits_one_event_when_a_frame_is_split_across_chunks", async () => {
    const events = await collect(streamOf(["event: tok", 'en\ndata: {"text":"Hi"}\n', "\n"]));
    expect(events).toEqual([{ type: "token", data: { text: "Hi" } }]);
  });

  it("decodes_vietnamese_split_inside_a_multibyte_character", async () => {
    const bytes = new TextEncoder().encode('event: token\ndata: {"text":"Đà Lạt"}\n\n');
    const insideD = 'event: token\ndata: {"text":"'.length + 1;
    const events = await collect(byteStreamOf([bytes.slice(0, insideD), bytes.slice(insideD)]));
    expect(events).toEqual([{ type: "token", data: { text: "Đà Lạt" } }]);
  });

  it("ignores_comment_lines_and_unknown_event_types", async () => {
    const events = await collect(streamOf([": ping\n\n", "event: other\ndata: {}\n\n", ": x\nevent: done\ndata: {}\n\n"]));
    expect(events).toEqual([{ type: "done", data: {} }]);
  });

  it("drops_a_half_frame_left_when_the_stream_ends", async () => {
    const events = await collect(streamOf(['event: token\ndata: {"text":"a"}\n\nevent: token\ndata: {"te']));
    expect(events).toEqual([{ type: "token", data: { text: "a" } }]);
  });

  it("stops_when_the_signal_aborts", async () => {
    const controller = new AbortController();
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(new TextEncoder().encode('event: token\ndata: {"text":"a"}\n\n'));
      },
    });
    const events: ChatEvent[] = [];
    for await (const event of parseSse(body, controller.signal)) {
      events.push(event);
      controller.abort();
    }
    expect(events).toHaveLength(1);
  });
});
