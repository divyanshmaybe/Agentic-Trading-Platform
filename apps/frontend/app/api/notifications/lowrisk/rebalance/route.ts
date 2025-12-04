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

    // Get portfolio server URL from environment
    const portfolioServerUrl =
      process.env.NEXT_PUBLIC_PORTFOLIO_API_URL ||
      process.env.NEXT_PUBLIC_PORTFOLIO_SERVER_URL ||
      process.env.PORTFOLIO_SERVER_URL ||
      "http://localhost:8000";

    // Get auth token from cookie
    const accessToken = request.cookies.get("access_token")?.value;

    // Default fund allocation: ₹100,000
    const fundAllocated = 100000.0;

    // Call trigger API to start the pipeline
    const headers: HeadersInit = {
      "Content-Type": "application/json",
    };
    if (accessToken) {
      headers["Authorization"] = `Bearer ${accessToken}`;
    }

    const triggerResponse = await fetch(
      `${portfolioServerUrl}/api/low-risk/trigger`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          fund_allocated: fundAllocated,
        }),
      }
    );

    let triggerData: any = null;
    let triggerSuccess = false;

    if (triggerResponse.ok) {
      const contentType = triggerResponse.headers.get("content-type");
      if (contentType && contentType.includes("application/json")) {
        triggerData = await triggerResponse.json();
        triggerSuccess = triggerData.success || false;
      } else {
        const text = await triggerResponse.text();
        console.warn(
          `[LowRisk Rebalance] Trigger API returned non-JSON: ${text.substring(0, 100)}`
        );
      }
    } else {
      const errorText = await triggerResponse.text().catch(() => "");
      console.error(
        `[LowRisk Rebalance] Trigger API failed: ${triggerResponse.status} - ${errorText}`
      );
    }

    return new Response(
      JSON.stringify({
        success: true,
        deletedCount: result.count,
        message: `Successfully cleared ${result.count} event(s) and triggered pipeline`,
        triggerSuccess,
        triggerMessage: triggerData?.message || null,
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

