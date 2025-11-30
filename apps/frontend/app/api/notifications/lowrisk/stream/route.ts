import { NextRequest } from "next/server";
import { LowRiskSubscriber } from "../../lib/lowrisk-sub";
import { enqueueSseEvent, textEncoder } from "../../lib/sse";
import { getAuthenticatedUser, getPrismaClient } from "../../lib/helpers";
import type { LowRiskEventDTO } from "@/lib/types/lowrisk";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(request: NextRequest) {
  // Authenticate user
  const auth = await getAuthenticatedUser(request);
  if (!auth.valid || !auth.user) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }

  const userId = auth.user._id;
  const prisma = getPrismaClient();
  let closed = false;
  let unsubscribe: (() => void) | null = null;

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const isCancelled = () => closed;

      try {
        // Send initial retry interval
        controller.enqueue(textEncoder.encode("retry: 5000\n\n"));

        // Query DB for initial low-risk events
        const initialEvents = await prisma.lowRiskEvent.findMany({
          where: { userId },
          orderBy: { createdAt: "asc" },
        });

        // Convert Date objects to ISO strings
        const eventDTOs: LowRiskEventDTO[] = initialEvents.map((event) => ({
          id: event.id,
          userId: event.userId,
          kind: event.kind as "log" | "notification",
          eventType: event.eventType,
          status: event.status,
          content: event.content,
          rawPayload: event.rawPayload,
          createdAt: event.createdAt.toISOString(),
          eventTime: event.eventTime ? event.eventTime.toISOString() : null,
        }));

        console.log(
          `[LowRisk SSE] Fetched ${eventDTOs.length} historical events for user ${userId}`
        );

        // Send initial events
        for (const event of eventDTOs) {
          enqueueSseEvent(controller, "lowrisk", event, isCancelled);
        }

        enqueueSseEvent(
          controller,
          "status",
          { status: "ready", count: eventDTOs.length },
          isCancelled
        );

        // Subscribe to Redis PubSub
        const subscription = await LowRiskSubscriber.subscribe(
          userId,
          (event) => {
            if (closed) {
              return;
            }
            enqueueSseEvent(controller, "lowrisk", event, isCancelled);
          }
        );
        unsubscribe = subscription.unsubscribe;

        // Keep-alive ping
        const keepAliveTimer = setInterval(() => {
          if (!closed) {
            enqueueSseEvent(controller, "ping", { ts: Date.now() }, isCancelled);
          }
        }, 15000);

        // Cleanup on close
        request.signal.addEventListener("abort", () => {
          clearInterval(keepAliveTimer);
          if (unsubscribe) {
            unsubscribe();
          }
          closed = true;
        });
      } catch (error) {
        console.error("[LowRisk SSE] Error:", error);
        enqueueSseEvent(
          controller,
          "error",
          { message: error instanceof Error ? error.message : "Unknown error" },
          isCancelled
        );
        closed = true;
      } finally {
        await prisma.$disconnect();
      }
    },
    async cancel() {
      closed = true;
      if (unsubscribe) {
        unsubscribe();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-store",
      connection: "keep-alive",
      pragma: "no-cache",
    },
  });
}

