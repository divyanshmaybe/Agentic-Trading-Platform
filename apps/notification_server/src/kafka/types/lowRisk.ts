/**
 * Type definitions for low-risk pipeline events
 */

/**
 * Low-risk log event payload from Kafka
 * Note: Timestamp fields in payload are ignored - eventTime comes from Kafka message timestamp only
 */
export interface LowRiskLogPayload {
  user_id: string;
  level?: string;
  message?: string;
  stage?: string;
  [key: string]: any;
}

/**
 * Low-risk notification event payload from Kafka
 * Note: Timestamp fields in payload are ignored - eventTime comes from Kafka message timestamp only
 */
export interface LowRiskNotificationPayload {
  user_id: string;
  type: string;
  status: "fetching" | "fetched" | string;
  content: Record<string, any>;
  [key: string]: any;
}

/**
 * Union type for low-risk payloads
 */
export type LowRiskPayload = LowRiskLogPayload | LowRiskNotificationPayload;

/**
 * Normalized low-risk event (server-side representation)
 * eventTime is ALWAYS derived from Kafka message timestamp, never from payload
 */
export type LowRiskNormalized = {
  userId: string; // normalized camelCase
  kind: "log" | "notification";
  eventType?: string | null;
  status?: string | null;
  content?: any | null;
  rawPayload: any;
  eventTime: Date; // Required - strictly from Kafka message timestamp
  topic: string;
  partition: number;
  offset: string;
};

