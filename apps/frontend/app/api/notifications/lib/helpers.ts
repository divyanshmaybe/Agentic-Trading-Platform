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
 * Get Prisma client instance
 */
export function getPrismaClient(): PrismaClient {
  return new PrismaClient({
    datasources: {
      db: {
        url: process.env.DATABASE_URL,
      },
    },
  });
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
      console.warn(`[Notifications] State table for ${channel} may not exist yet:`, error);
      dismissedNotificationIds = [];
    }
  }

  const dismissedIds = new Set(
    dismissedNotificationIds.map((d: { notificationId: string }) => d.notificationId)
  );

  // Fetch all notifications and filter out dismissed ones
  const notifications = await prisma.notification.findMany({
    where: {
      id: {
        notIn: dismissedIds.size > 0 ? Array.from(dismissedIds) : [],
      },
    },
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
 * Dashboard only receives: stock_recommendation, news_sentiment
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

