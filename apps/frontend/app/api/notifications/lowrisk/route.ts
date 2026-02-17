import { NextRequest } from "next/server";
import { getAuthenticatedUser, getPrismaClient } from "../lib/helpers";
import type { LowRiskEventDTO } from "@/lib/types/lowrisk";

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
    // Query all low-risk events for the user
    const events = await prisma.lowRiskEvent.findMany({
      where: { userId },
      orderBy: { createdAt: "asc" },
    });

    // Convert Date objects to ISO strings
        const eventDTOs: LowRiskEventDTO[] = events.map((event) => ({
          id: event.id,
          userId: event.userId,
          kind: event.kind as "info" | "industry" | "stock" | "report" | "reasoning" | "summary" | "stage",
          eventType: event.eventType,
          status: event.status,
          content: event.content,
          rawPayload: event.rawPayload,
          createdAt: event.createdAt.toISOString(),
          eventTime: event.eventTime ? event.eventTime.toISOString() : null,
        }));

    console.log(
      `[LowRisk GET] Fetched ${eventDTOs.length} events for user ${userId}`
    );

    return new Response(JSON.stringify(eventDTOs), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  } catch (error) {
    console.error("[LowRisk GET] Error:", error);
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

