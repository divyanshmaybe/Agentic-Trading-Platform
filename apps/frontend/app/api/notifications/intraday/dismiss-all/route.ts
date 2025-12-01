import { NextRequest } from "next/server";
import {
  getAuthenticatedUser,
  getPrismaClient,
  getNotificationsFromDB,
  shouldForwardToIntraday,
} from "../../lib/helpers";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
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
    // Get all non-dismissed notifications
    const notifications = await getNotificationsFromDB(prisma, userId, "intraday");

    // Intraday shows ALL notifications
    const filteredNotifications = notifications.filter(shouldForwardToIntraday);

    if (filteredNotifications.length === 0) {
      return new Response(JSON.stringify({ success: true, count: 0 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }

    // Upsert dismiss records for all notifications
    // Note: Type assertion used because Prisma client needs to be regenerated after schema changes
    const prismaAny = prisma as any;
    await prismaAny.$transaction(
      filteredNotifications.map((notification) =>
        prismaAny.intradayNotificationState.upsert({
          where: {
            userId_notificationId: {
              userId,
              notificationId: notification.id,
            },
          },
          create: {
            userId,
            notificationId: notification.id,
          },
          update: {},
        })
      )
    );

    return new Response(
      JSON.stringify({ success: true, count: filteredNotifications.length }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      }
    );
  } catch (error) {
    console.error("[Intraday Dismiss All] Error:", error);
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

