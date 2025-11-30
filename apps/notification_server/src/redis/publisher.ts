import { RedisManager } from "../../../../shared/js/redisManager";
import { Notification } from "@prisma/client";
import { LowRiskNormalized } from "../kafka/types/lowRisk";

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

export class LowRiskPublisher {
  private redis: RedisManager;

  constructor(redis: RedisManager) {
    this.redis = redis;
  }

  /**
   * Publish a low-risk event to Redis per-user channel
   * @param event - Strongly-typed normalized event with DB fields (id, createdAt)
   */
  async publish(event: LowRiskNormalized & { id: string; createdAt: Date }): Promise<void> {
    if (!this.redis.isReady()) {
      console.warn("[Redis][LowRisk] Not connected, skipping publish");
      return;
    }

    try {
      const channel = `lowrisk:user:${event.userId}`;
      
      // Serialize with proper Date handling
      // eventTime is always a Date (required, non-nullable) - from Kafka message timestamp only
      const payload = {
        id: event.id,
        userId: event.userId,
        kind: event.kind,
        eventType: event.eventType ?? null,
        status: event.status ?? null,
        content: event.content ?? null,
        rawPayload: event.rawPayload,
        eventTime: event.eventTime.toISOString(), // Always present - from Kafka timestamp
        createdAt: event.createdAt.toISOString(),
      };
      const message = JSON.stringify(payload);

      const connection = this.redis.getConnection();
      if (connection) {
        await connection.publish(channel, message);
        console.log(`[Redis][LowRisk] Published ${event.id} to lowrisk:user:${event.userId}`);
      }
    } catch (error) {
      console.error("[Redis][LowRisk] Failed to publish event:", error);
      throw error; // Re-throw so caller can handle if needed
    }
  }
}
