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
  
  // Get lastEventId from query params to resume from where we left off
  const { searchParams } = new URL(request.url);
  const lastEventId = searchParams.get("lastEventId");
  const lastEventCreatedAt = searchParams.get("lastEventCreatedAt");
  
  let closed = false;
  let unsubscribe: (() => void) | null = null;
  let keepAliveTimer: NodeJS.Timeout | null = null;

  const closeStream = () => {
    if (closed) return;
    closed = true;
    if (keepAliveTimer) {
      clearInterval(keepAliveTimer);
      keepAliveTimer = null;
    }
    if (unsubscribe) {
      unsubscribe();
      unsubscribe = null;
    }
  };

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const isCancelled = () => closed;

      try {
        // Send initial retry interval
        controller.enqueue(textEncoder.encode("retry: 5000\n\n"));

        // Build query to fetch only events after the last known event
        const whereClause: any = { userId };
        
        if (lastEventId || lastEventCreatedAt) {
          // If we have a lastEventId, find that event first to get its createdAt
          if (lastEventId) {
            const lastEvent = await prisma.lowRiskEvent.findUnique({
              where: { id: lastEventId },
              select: { createdAt: true },
            });
            
            if (lastEvent) {
              // Fetch events created after the last event's createdAt
              whereClause.createdAt = { gt: lastEvent.createdAt };
            }
          } else if (lastEventCreatedAt) {
            // If we have a timestamp directly, use it
            const lastCreatedAt = new Date(lastEventCreatedAt);
            whereClause.createdAt = { gt: lastCreatedAt };
          }
        }

        // Query DB for events after the last known event (or all if no lastEventId)
        const initialEvents = await prisma.lowRiskEvent.findMany({
          where: whereClause,
          orderBy: { createdAt: "asc" },
        });

        // Convert Date objects to ISO strings
        const eventDTOs: LowRiskEventDTO[] = initialEvents.map((event) => ({
          id: event.id,
          userId: event.userId,
          kind: event.kind as "info" | "industry" | "stock" | "report" | "reasoning" | "summary" | "stage",
          eventType: event.eventType,
          status: event.status,
          content: event.content,
          rawPayload: event.rawPayload,
          createdAt: event.createdAt.toISOString(),
          eventTime: event.eventTime ? event.eventTime.toISOString() : null,
        }));

        console.log(
          `[LowRisk SSE] Fetched ${eventDTOs.length} historical events for user ${userId}${lastEventId ? ` (resuming after event ${lastEventId})` : ""}`
        );

        // Send initial events
        for (const event of eventDTOs) {
          enqueueSseEvent(controller, "lowrisk", event, isCancelled);
          
          // Close stream after summary event
          if (event.kind === "summary") {
            console.log(`[LowRisk SSE] Summary event sent, closing stream for user ${userId}`);
            closeStream();
            controller.close();
            return;
          }
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
            
            // Close stream after summary event
            if (event.kind === "summary") {
              console.log(`[LowRisk SSE] Summary event received, closing stream for user ${userId}`);
              closeStream();
              controller.close();
            }
          }
        );
        unsubscribe = subscription.unsubscribe;

        // Keep-alive ping
        keepAliveTimer = setInterval(() => {
          if (!closed) {
            enqueueSseEvent(controller, "ping", { ts: Date.now() }, isCancelled);
          }
        }, 15000);

        // Cleanup on close
        request.signal.addEventListener("abort", () => {
          closeStream();
        });
      } catch (error) {
        console.error("[LowRisk SSE] Error:", error);
        enqueueSseEvent(
          controller,
          "error",
          { message: error instanceof Error ? error.message : "Unknown error" },
          isCancelled
        );
        closeStream();
      }
    },
    async cancel() {
      closeStream();
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

