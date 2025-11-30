/**
 * Type definitions for low-risk pipeline events
 */

/**
 * Low-risk log event payload from Kafka
 */
export interface LowRiskLogPayload {
  user_id: string;
  timestamp?: string | number;
  level?: string;
  message?: string;
  stage?: string;
  [key: string]: any;
}

/**
 * Low-risk notification event payload from Kafka
 */
export interface LowRiskNotificationPayload {
  user_id: string;
  type: string;
  status: "fetching" | "fetched" | string;
  content: Record<string, any>;
  timestamp?: string | number;
  [key: string]: any;
}

/**
 * Union type for low-risk payloads
 */
export type LowRiskPayload = LowRiskLogPayload | LowRiskNotificationPayload;

/**
 * Normalized low-risk event (server-side representation)
 */
export type LowRiskNormalized = {
  userId: string; // normalized camelCase
  kind: "log" | "notification";
  eventType?: string | null;
  status?: string | null;
  content?: any | null;
  rawPayload: any;
  eventTime?: Date | null;
  topic: string;
  partition: number;
  offset: string;
};

