import { CHAT_EVENT_TYPES, type ChatEvent } from "./api.types.ts";

const FRAME_END = "\n\n";

// Read a text/event-stream body as chat events; split frames and split UTF-8 characters are buffered
export async function* parseSse(body: ReadableStream<Uint8Array>, signal: AbortSignal): AsyncGenerator<ChatEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  // Cancelling the reader ends a pending read, so an abort stops the loop at once
  const handleAbort = () => {
    reader.cancel().catch(() => undefined);
  };
  signal.addEventListener("abort", handleAbort, { once: true });

  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done || signal.aborted) return;

      // Stream mode keeps a multi-byte character that straddles two reads whole
      buffer += decoder.decode(value, { stream: true });

      // Emit the complete frames; the tail waits for the next read
      for (let end = buffer.indexOf(FRAME_END); end !== -1; end = buffer.indexOf(FRAME_END)) {
        const event = toChatEvent(buffer.slice(0, end));
        buffer = buffer.slice(end + FRAME_END.length);
        if (event !== null) yield event;
        if (signal.aborted) return;
      }
    }
  } finally {
    signal.removeEventListener("abort", handleAbort);
    reader.releaseLock();
  }
}

// One frame as a chat event; null for comments, unknown types and broken JSON
function toChatEvent(frame: string): ChatEvent | null {
  let type = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!(CHAT_EVENT_TYPES as readonly string[]).includes(type) || data.length === 0) return null;

  try {
    const parsed: unknown = JSON.parse(data.join("\n"));
    if (typeof parsed !== "object" || parsed === null) return null;
    // The type is a known one; the payload shape per type is the backend's contract
    return { type, data: parsed } as ChatEvent;
  } catch {
    return null;
  }
}
