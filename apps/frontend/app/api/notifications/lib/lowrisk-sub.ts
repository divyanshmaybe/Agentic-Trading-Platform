import IORedis from "ioredis";
import type { LowRiskEventDTO } from "@/lib/types/lowrisk";

type LowRiskCallback = (event: LowRiskEventDTO) => void;

/**
 * Per-request Redis PubSub subscriber for low-risk events
 * Creates a fresh IORedis connection per subscription
 * Subscribes to per-user channel: lowrisk:user:<userId>
 */
export class LowRiskSubscriber {
  /**
   * Subscribe to low-risk events for a specific user
   * Creates a fresh Redis connection for this subscription
   * Returns an unsubscribe function that closes the connection
   */
  public static async subscribe(
    userId: string,
    callback: LowRiskCallback
  ): Promise<{ unsubscribe: () => void }> {
    const channel = `lowrisk:user:${userId}`;
    let subscriber: IORedis | null = null;
    let isSubscribed = false;

    try {
      // Create a dedicated subscriber connection
      // IORedis requires separate connections for pub/sub
      const redisUrl = process.env.REDIS_URL;
      if (redisUrl) {
        subscriber = new IORedis(redisUrl, {
          maxRetriesPerRequest: null,
          enableAutoPipelining: false,
        });
      } else {
        subscriber = new IORedis({
          host: process.env.REDIS_HOST || "localhost",
          port: Number(process.env.REDIS_PORT) || 6379,
          password: process.env.REDIS_PASSWORD || undefined,
          maxRetriesPerRequest: null,
          enableAutoPipelining: false,
        });
      }

      // Subscribe to the channel
      await subscriber.subscribe(channel);
      isSubscribed = true;

      console.log(`[LowRisk SSE] Subscribed to channel: ${channel}`);

      // Listen for messages
      subscriber.on("message", (msgChannel, message) => {
        if (msgChannel === channel) {
          try {
            const event: LowRiskEventDTO = JSON.parse(message);
            console.log(
              `[LowRisk SSE] Received realtime low-risk event for user ${userId}`
            );
            callback(event);
          } catch (error) {
            console.error(
              "[LowRisk SSE] Failed to parse low-risk event message:",
              error
            );
          }
        }
      });

      subscriber.on("error", (error) => {
        console.error("[LowRisk SSE] Redis subscriber error:", error);
        isSubscribed = false;
      });
    } catch (error) {
      console.error("[LowRisk SSE] Failed to setup subscription:", error);
      isSubscribed = false;
      // Clean up if connection was created but subscription failed
      if (subscriber) {
        try {
          await subscriber.quit();
        } catch (quitError) {
          console.error("[LowRisk SSE] Error closing subscriber:", quitError);
        }
        subscriber = null;
      }
    }

    // Return unsubscribe function
    // Note: This is async but can be called without await in cleanup handlers
    return {
      unsubscribe: () => {
        if (!subscriber || !isSubscribed) {
          return;
        }
        
        const subToClose = subscriber;
        subscriber = null;
        isSubscribed = false;
        
        // Fire and forget - don't block cleanup
        (async () => {
          try {
            // Check if connection is still valid before unsubscribing
            if (subToClose.status === "ready" || subToClose.status === "connect") {
              await subToClose.unsubscribe(channel);
            }
            // Always try to quit, even if unsubscribe failed
            if (subToClose.status !== "end" && subToClose.status !== "close") {
              await subToClose.quit();
            }
            console.log(
              `[LowRisk SSE] Unsubscribed from lowrisk:user:${userId}`
            );
          } catch (error) {
            // Silently handle errors - connection might already be closed
            if (error instanceof Error && !error.message.includes("Connection is closed")) {
              console.error("[LowRisk SSE] Error unsubscribing:", error);
            }
            // Try to disconnect anyway
            try {
              subToClose.disconnect();
            } catch (disconnectError) {
              // Ignore disconnect errors
            }
          }
        })();
      },
    };
  }
}

