import { NextRequest } from "next/server";
import { NotificationSubscriber } from "../../lib/pubsub";
import { enqueueSseEvent, textEncoder } from "../../lib/sse";
import {
  getAuthenticatedUser,
  getPrismaClient,
  getNotificationsFromDB,
  shouldForwardToIntraday,
} from "../../lib/helpers";
import type { NotificationDTO } from "@/lib/types/notifications";

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

        // Query DB for initial notifications
        const initialNotifications = await getNotificationsFromDB(
          prisma,
          userId,
          "intraday"
        );

        // Intraday shows ALL notifications (no filtering)
        const filteredNotifications = initialNotifications.filter(
          shouldForwardToIntraday
        );

        // Send initial notifications
        for (const notification of filteredNotifications) {
          enqueueSseEvent(controller, "notification", notification, isCancelled);
        }

        enqueueSseEvent(
          controller,
          "status",
          { status: "ready", count: filteredNotifications.length },
          isCancelled
        );

        // Subscribe to Redis PubSub
        const subscriber = NotificationSubscriber.getInstance();
        unsubscribe = await subscriber.subscribe((notification) => {
          if (closed) {
            return;
          }

          // NotificationMessage from PubSub already has ISO strings (NotificationDTO format)
          // Intraday forwards ALL notifications - send as-is (no Date conversion needed)
          if (shouldForwardToIntraday(notification as NotificationDTO)) {
            enqueueSseEvent(controller, "notification", notification, isCancelled);
          }
        });

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
        console.error("[Intraday SSE] Error:", error);
        enqueueSseEvent(
          controller,
          "error",
          { message: error instanceof Error ? error.message : "Unknown error" },
          isCancelled
        );
        closed = true;
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
