import { NextRequest } from "next/server";
import {
  getAuthenticatedUser,
  getPrismaClient,
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
    const body = await request.json();
    const { notificationIds } = body;

    if (!Array.isArray(notificationIds) || notificationIds.length === 0) {
      return new Response(
        JSON.stringify({ error: "notificationIds must be a non-empty array" }),
        {
          status: 400,
          headers: { "content-type": "application/json" },
        }
      );
    }

    // Upsert dismiss records
    // Note: Type assertion used because Prisma client needs to be regenerated after schema changes
    const prismaAny = prisma as any;
    await prismaAny.$transaction(
      notificationIds.map((notificationId: string) =>
        prismaAny.intradayNotificationState.upsert({
          where: {
            userId_notificationId: {
              userId,
              notificationId,
            },
          },
          create: {
            userId,
            notificationId,
          },
          update: {},
        })
      )
    );

    return new Response(JSON.stringify({ success: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  } catch (error) {
    console.error("[Intraday Dismiss] Error:", error);
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
