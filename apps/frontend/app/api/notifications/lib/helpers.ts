import { NextRequest } from "next/server";
import { PrismaClient } from "@prisma/client";
import type { NotificationDTO } from "@/lib/types/notifications";

const AUTH_BASE_URL = process.env.AUTH_SERVER_URL || "http://localhost:4000";

export interface AuthUser {
  _id: string;
  email: string;
  firstName: string;
  lastName: string;
  role: "admin" | "staff" | "viewer";
  organizationId: string;
  username: string;
}

/**
 * Internal Notification type with Date objects (for DB queries)
 * Converted to NotificationDTO before returning to clients
 */
export interface Notification {
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
  createdAt: Date;
  eventTime: Date | null;
}

/**
 * Validate token with auth service and return user
 */
export async function getAuthenticatedUser(
  request: NextRequest
): Promise<{ valid: boolean; user?: AuthUser }> {
  const accessToken = request.cookies.get("access_token")?.value;

  if (!accessToken) {
    return { valid: false };
  }

  try {
    const response = await fetch(
      `${AUTH_BASE_URL}/api/internal/validate-token`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Internal-Service": "true",
          "X-Service-Secret": process.env.INTERNAL_SERVICE_SECRET || "",
        },
        body: JSON.stringify({ token: accessToken }),
      }
    );

    if (!response.ok) {
      return { valid: false };
    }

    const data = await response.json();
    return { valid: true, user: data.user };
  } catch (error) {
    console.error("Token validation error:", error);
    return { valid: false };
  }
}

/**
 * Prisma Client Singleton
 * 
 * CRITICAL: This singleton pattern prevents connection pool exhaustion.
 * Each PrismaClient instance creates its own connection pool (~10 connections).
 * Without a singleton, each request would create a new client, quickly exhausting
 * the database connection limit.
 * 
 * The global object persists across hot reloads in Next.js development,
 * ensuring we reuse the same client instance.
 */
declare global {
  // eslint-disable-next-line no-var
  var __prisma: PrismaClient | undefined;
}

/**
 * Get Prisma client instance (singleton pattern)
 * 
 * Reuses existing client or creates a new one if needed.
 * This ensures only ONE connection pool exists across all requests.
 */
export function getPrismaClient(): PrismaClient {
  // Check if DATABASE_URL is set
  const databaseUrl = process.env.DATABASE_URL;
  
  if (!databaseUrl) {
    console.error("[getPrismaClient] ERROR: DATABASE_URL environment variable is not set!");
    console.error("[getPrismaClient] Please set DATABASE_URL in your .env file or environment variables.");
    throw new Error("DATABASE_URL environment variable is required but not set");
  }

  // Reuse existing client if available (singleton pattern)
  // In Next.js, global object persists across hot reloads
  if (global.__prisma) {
    return global.__prisma;
  }

  // Create new client - Prisma manages its own connection pool internally
  const prisma = new PrismaClient({
    log: process.env.NODE_ENV === "development" ? ["error", "warn"] : ["error"],
  });

  // Store in global for reuse across requests and hot reloads
  global.__prisma = prisma;

  if (process.env.NODE_ENV === "development") {
    console.log("[getPrismaClient] ✅ Created Prisma client singleton (should only see this once)");
  }

  return prisma;
}

/**
 * Get notifications from DB excluding dismissed ones
 * Uses Prisma's type-safe queries for better reliability
 * Returns NotificationDTO with ISO strings for createdAt/eventTime
 */
export async function getNotificationsFromDB(
  prisma: PrismaClient,
  userId: string,
  channel: "dashboard" | "intraday"
): Promise<NotificationDTO[]> {
  // Get all dismissed notification IDs for this user and channel
  // Using bracket notation to access models that may not be in generated client yet
  const stateModel = channel === "dashboard" 
    ? (prisma as any).dashboardNotificationState 
    : (prisma as any).intradayNotificationState;

  let dismissedNotificationIds: Array<{ notificationId: string }> = [];
  
  if (stateModel) {
    try {
      dismissedNotificationIds = await stateModel.findMany({
        where: { userId },
        select: { notificationId: true },
      });
    } catch (error) {
      // If tables don't exist yet (migrations not run), just return all notifications
      console.warn(`[getNotificationsFromDB] State table for ${channel} may not exist yet:`, error);
      dismissedNotificationIds = [];
    }
  } else {
    console.warn(`[getNotificationsFromDB] State model for channel ${channel} is null/undefined`);
  }

  const dismissedIds = new Set(
    dismissedNotificationIds.map((d: { notificationId: string }) => d.notificationId)
  );

  // Build query filter to exclude dismissed notifications
  // Category filtering is done at the route level (like intraday does)
  const queryFilter: any = {};
  
  // Filter out dismissed notifications (where dismiss state DOESN'T exist for this userId + notificationId)
  if (dismissedIds.size > 0) {
    queryFilter.id = { notIn: Array.from(dismissedIds) };
  }

  // OPTIMIZED: Single query to get notifications (removed 3 unnecessary count queries)
  // This reduces connection usage from 5 queries per request to 2 queries per request
  const notifications = await prisma.notification.findMany({
    where: queryFilter,
    orderBy: {
      createdAt: "desc",
    },
  });

  // Convert Date objects to ISO strings for NotificationDTO
  return notifications.map((n) => ({
    id: n.id,
    kafkaKey: n.kafkaKey,
    topic: n.topic,
    category: n.category,
    title: n.title,
    summary: n.summary,
    symbol: n.symbol,
    sector: n.sector,
    sentiment: n.sentiment,
    signal: n.signal,
    confidence: n.confidence,
    url: n.url,
    rawPayload: n.rawPayload,
    createdAt: n.createdAt.toISOString(),
    eventTime: n.eventTime ? n.eventTime.toISOString() : null,
  }));
}

/**
 * Check if notification should be forwarded to dashboard
 * Dashboard receives: stock_recommendation, news_sentiment
 */
export function shouldForwardToDashboard(notification: NotificationDTO | Notification): boolean {
  return (
    notification.category === "stock_recommendation" ||
    notification.category === "news_sentiment"
  );
}

/**
 * Check if notification should be forwarded to intraday
 * Intraday receives ALL notifications
 */
export function shouldForwardToIntraday(notification: NotificationDTO | Notification): boolean {
  return true;
}

