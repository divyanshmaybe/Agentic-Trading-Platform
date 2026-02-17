/**
 * LowRiskEventDTO - Canonical type for low-risk event data from Redis PubSub and REST API
 * This matches the structure of the LowRiskEvent Prisma model
 */
export interface LowRiskEventDTO {
  id: string;
  userId: string;
  kind: "info" | "industry" | "stock" | "report" | "reasoning" | "summary" | "stage";
  eventType: string | null;   // "industry" | "stock" | "report" | null (null for info/reasoning/summary/stage)
  status: string | null;      // "fetching" | "fetched" | "generating" | "generated" | "thinking" | "progress" | null
  content: any | null;
  rawPayload: any;
  createdAt: string; // ISO string
  eventTime: string | null; // ISO string or null
}
