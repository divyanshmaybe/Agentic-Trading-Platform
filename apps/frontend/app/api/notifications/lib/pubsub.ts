import { RedisManager } from "../../../../../../shared/js/redisManager";
import IORedis from "ioredis";

export interface NotificationMessage {
  id: string;
  kafkaKey: string | null;
  topic: string;
  category: string;
  title: string | null;
  summary: string | null;
  symbol: string | null;
  sector: string | null;
  sentiment: string | null;
  signal: string | null;
  confidence: number | null;
  url: string | null;
  rawPayload: any;
  createdAt: string;
  eventTime: string | null;
}

type NotificationCallback = (notification: NotificationMessage) => void;

/**
 * Singleton Redis PubSub subscriber for notifications
 * Subscribes to the 'notifications:new' channel
 */
export class NotificationSubscriber {
  private static instance: NotificationSubscriber | null = null;
  private redis: RedisManager;
  private subscriber: IORedis | null = null;
  private subscribers: Set<NotificationCallback> = new Set();
  private channel: string = "notifications:new";
  private isSubscribed: boolean = false;

  private constructor() {
    this.redis = RedisManager.getInstance();
  }

  public static getInstance(): NotificationSubscriber {
    if (!NotificationSubscriber.instance) {
      NotificationSubscriber.instance = new NotificationSubscriber();
    }
    return NotificationSubscriber.instance;
  }

  /**
   * Subscribe to notifications
   * Returns a cleanup function to unsubscribe
   */
  public async subscribe(callback: NotificationCallback): Promise<() => void> {
    this.subscribers.add(callback);

    // If already subscribed, just add the callback
    if (this.isSubscribed) {
      return () => {
        this.subscribers.delete(callback);
      };
    }

    // Otherwise, set up the subscription
    await this.setupSubscription();

    return () => {
      this.subscribers.delete(callback);
      // If no more subscribers, we could unsubscribe, but keep connection alive
      // for potential future subscribers
    };
  }

  private async setupSubscription(): Promise<void> {
    if (this.isSubscribed) {
      return;
    }

    try {
      await this.redis.connect();
      const connection = this.redis.getConnection();

      if (!connection) {
        console.warn("[PubSub] Redis connection not available");
        return;
      }

      // Create a dedicated subscriber connection
      // IORedis requires separate connections for pub/sub
      const redisUrl = process.env.REDIS_URL;
      if (redisUrl) {
        this.subscriber = new IORedis(redisUrl, {
          maxRetriesPerRequest: null,
          enableAutoPipelining: false,
        });
      } else {
        this.subscriber = new IORedis({
          host: process.env.REDIS_HOST || "localhost",
          port: Number(process.env.REDIS_PORT) || 6379,
          password: process.env.REDIS_PASSWORD || undefined,
          maxRetriesPerRequest: null,
          enableAutoPipelining: false,
        });
      }

      // Subscribe to the channel
      await this.subscriber.subscribe(this.channel);
      this.isSubscribed = true;

      console.log(`[PubSub] Subscribed to channel: ${this.channel}`);

      // Listen for messages
      this.subscriber.on("message", (channel, message) => {
        if (channel === this.channel) {
          try {
            const notification: NotificationMessage = JSON.parse(message);
            // Notify all subscribers
            this.subscribers.forEach((callback) => {
              try {
                callback(notification);
              } catch (error) {
                console.error("[PubSub] Error in subscriber callback:", error);
              }
            });
          } catch (error) {
            console.error("[PubSub] Failed to parse notification message:", error);
          }
        }
      });

      this.subscriber.on("error", (error) => {
        console.error("[PubSub] Redis subscriber error:", error);
        this.isSubscribed = false;
      });
    } catch (error) {
      console.error("[PubSub] Failed to setup subscription:", error);
      this.isSubscribed = false;
    }
  }

  /**
   * Unsubscribe from Redis (cleanup)
   */
  public async unsubscribe(): Promise<void> {
    if (this.subscriber) {
      try {
        await this.subscriber.unsubscribe(this.channel);
        await this.subscriber.quit();
        this.subscriber = null;
        this.isSubscribed = false;
        console.log("[PubSub] Unsubscribed from channel");
      } catch (error) {
        console.error("[PubSub] Error unsubscribing:", error);
      }
    }
    this.subscribers.clear();
  }
}

