export type StreamController = ReadableStreamDefaultController<Uint8Array>;

const textEncoder = new TextEncoder();

export function enqueueSseEvent(
  controller: StreamController,
  event: string,
  data: unknown,
  cancelled: () => boolean,
): void {
  if (cancelled()) {
    return;
  }

  try {
    const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
    controller.enqueue(textEncoder.encode(payload));
  } catch (error) {
    console.warn("[SSE] Failed to enqueue event:", error);
  }
}

export { textEncoder };

