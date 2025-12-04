import { NextRequest } from "next/server";
import { getAuthenticatedUser, getPrismaClient } from "../../lib/helpers";

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
    // Delete all low-risk events for this user
    const result = await prisma.lowRiskEvent.deleteMany({
      where: { userId },
    });

    console.log(
      `[LowRisk Rebalance] Deleted ${result.count} events for user ${userId}`
    );

    return new Response(
      JSON.stringify({
        success: true,
        deletedCount: result.count,
        message: `Successfully cleared ${result.count} event(s)`,
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      }
    );
  } catch (error) {
    console.error("[LowRisk Rebalance] Error:", error);
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

