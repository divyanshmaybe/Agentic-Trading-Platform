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
    const notifications = await getNotificationsFromDB(prisma, userId, "dashboard");

    console.log("[Dashboard GET] Fetched notifications from DB:", notifications.length);
    console.log("[Dashboard GET] User ID:", userId);
    
    if (notifications.length > 0) {
      const uniqueCategories = [...new Set(notifications.map(n => n.category))];
      const categoryCounts = uniqueCategories.map(cat => ({
        category: cat,
        count: notifications.filter(n => n.category === cat).length
      }));
      console.log("[Dashboard GET] All unique categories in DB:", uniqueCategories);
      console.log("[Dashboard GET] Category counts:", categoryCounts);
      console.log("[Dashboard GET] stock_recommendation count:", notifications.filter(n => n.category === "stock_recommendation").length);
      console.log("[Dashboard GET] news_sentiment count:", notifications.filter(n => n.category === "news_sentiment").length);
      console.log("[Dashboard GET] Sample notifications (first 10):", notifications.slice(0, 10).map(n => ({ 
        id: n.id, 
        category: n.category,
        title: n.title 
      })));
    } else {
      console.log("[Dashboard GET] No notifications found in database for any user");
    }

    // getNotificationsFromDB already filters for stock_recommendation and news_sentiment for dashboard channel
    // Additional safety filter to ensure only these two categories are returned
    const filteredNotifications: NotificationDTO[] = notifications.filter(
      (n) => n.category === "stock_recommendation" || n.category === "news_sentiment"
    );

    console.log("[Dashboard GET] After category filter:", filteredNotifications.length);
    console.log("[Dashboard GET] Expected categories: ['stock_recommendation', 'news_sentiment']");
    if (filteredNotifications.length > 0) {
      const filteredCategoryCounts = filteredNotifications.reduce((acc, n) => {
        acc[n.category] = (acc[n.category] || 0) + 1;
        return acc;
      }, {} as Record<string, number>);
      console.log("[Dashboard GET] Filtered category counts:", filteredCategoryCounts);
      console.log("[Dashboard GET] Filtered stock_recommendation:", filteredCategoryCounts["stock_recommendation"] || 0);
      console.log("[Dashboard GET] Filtered news_sentiment:", filteredCategoryCounts["news_sentiment"] || 0);
    }
    
    if (notifications.length > 0 && filteredNotifications.length === 0) {
      console.warn("[Dashboard GET] ⚠️  WARNING: Notifications exist in DB but none match category filter!");
      console.warn("[Dashboard GET] ⚠️  DB has categories:", [...new Set(notifications.map(n => n.category))]);
      console.warn("[Dashboard GET] ⚠️  Dashboard expects: ['stock_recommendation', 'news_sentiment']");
    }
    
    // Check specifically for stock_recommendation and news_sentiment
    const stockRecCount = notifications.filter(n => n.category === "stock_recommendation").length;
    const newsSentCount = notifications.filter(n => n.category === "news_sentiment").length;
    if (stockRecCount === 0 && newsSentCount === 0 && notifications.length > 0) {
      console.warn("[Dashboard GET] ⚠️  CRITICAL: No stock_recommendation or news_sentiment notifications found in DB!");
      console.warn("[Dashboard GET] ⚠️  Available categories:", [...new Set(notifications.map(n => n.category))]);
    }

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
  } finally {
    await prisma.$disconnect();
  }
}

