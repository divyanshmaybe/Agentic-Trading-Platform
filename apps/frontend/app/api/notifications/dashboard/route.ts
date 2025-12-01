import { NextRequest } from "next/server";
import {
  getAuthenticatedUser,
  getPrismaClient,
  getNotificationsFromDB,
  shouldForwardToDashboard,
} from "../lib/helpers";
import type { NotificationDTO } from "@/lib/types/notifications";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  // Authenticate user
  const auth = await getAuthenticatedUser(request);
  if (!auth.valid || !auth.user) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }

  const userId = auth.user._id;
  const prisma = getPrismaClient();

  try {
    // Get all notifications excluding dismissed ones (returns NotificationDTO[] with ISO strings)
    // Match intraday pattern: get all notifications, filter by category at route level
    const notifications = await getNotificationsFromDB(prisma, userId, "dashboard");

    // Dashboard only shows stock_recommendation and news_sentiment (filter at route level like intraday)
    const filteredNotifications: NotificationDTO[] = notifications.filter(shouldForwardToDashboard);

    return new Response(JSON.stringify(filteredNotifications), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  } catch (error) {
    console.error("[Dashboard GET] Error:", error);
    return new Response(
      JSON.stringify({
        error: error instanceof Error ? error.message : "Internal server error",
      }),
      {
        status: 500,
        headers: { "content-type": "application/json" },
      }
    );
  }
}
