/**
 * LowRiskEventDTO - Canonical type for low-risk event data from Redis PubSub and REST API
 * This matches the structure of the LowRiskEvent Prisma model
 */
export interface LowRiskEventDTO {
  id: string;
  userId: string;
  kind: "log" | "notification";
  eventType: string | null;
  status: string | null;
  content: any | null;
  rawPayload: any;
  createdAt: string; // ISO string
  eventTime: string | null; // ISO string or null
}
