import { RedisManager } from "../../../../shared/js/redisManager";
import { Notification } from "@prisma/client";

export class NotificationPublisher {
  private redis: RedisManager;
  private channel: string = "notifications:new";

  constructor(redis: RedisManager) {
    this.redis = redis;
  }

  private serializeNotification(notification: Notification): any {
    return {
      id: notification.id,
      kafkaKey: notification.kafkaKey,
      topic: notification.topic,
      category: notification.category,
      title: notification.title,
      summary: notification.summary,
      symbol: notification.symbol,
      sector: notification.sector,
      sentiment: notification.sentiment,
      signal: notification.signal,
      confidence: notification.confidence,
      url: notification.url,
      rawPayload: notification.rawPayload,
      createdAt: notification.createdAt.toISOString(),
      eventTime: notification.eventTime?.toISOString() || null,
    };
  }

  async publish(notification: Notification): Promise<void> {
    if (!this.redis.isReady()) {
      console.warn("[Redis] Not connected, skipping publish");
      return;
    }

    try {
      const serialized = this.serializeNotification(notification);
      const message = JSON.stringify(serialized);

      const connection = this.redis.getConnection();
      if (connection) {
        const result = await connection.publish(this.channel, message);
        console.log(`[Redis] Published notification: ${notification.id} to channel ${this.channel} (${result} subscribers)`);
      }
    } catch (error) {
      console.error("[Redis] Failed to publish notification:", error);
    }
  }
}
