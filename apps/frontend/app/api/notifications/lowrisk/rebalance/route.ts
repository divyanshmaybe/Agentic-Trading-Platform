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

    // Call REBALANCE API (not trigger) to re-trigger the pipeline with cooldown check
    const headers: HeadersInit = {
      "Content-Type": "application/json",
    };
    if (accessToken) {
      headers["Authorization"] = `Bearer ${accessToken}`;
    }

    const rebalanceResponse = await fetch(
      `${portfolioServerUrl}/api/low-risk/rebalance`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          fund_allocated: fundAllocated,
        }),
      }
    );

    // Parse response
    const contentType = rebalanceResponse.headers.get("content-type");
    if (!contentType || !contentType.includes("application/json")) {
      const text = await rebalanceResponse.text();
      console.error(
        `[LowRisk Rebalance] API returned non-JSON: ${text.substring(0, 100)}`
      );
      return new Response(
        JSON.stringify({
          success: false,
          message: "Invalid response from rebalance API",
        }),
        {
          status: 500,
          headers: { "content-type": "application/json" },
        }
      );
    }

    const rebalanceData = await rebalanceResponse.json();

    // Check if rebalance was successful
    if (!rebalanceResponse.ok || !rebalanceData.success) {
      // Return the error (including 6-month cooldown errors)
      return new Response(
        JSON.stringify({
          success: false,
          message: rebalanceData.message || "Failed to rebalance",
          error: rebalanceData.message || "Failed to rebalance",
        }),
        {
          status: rebalanceResponse.status,
          headers: { "content-type": "application/json" },
        }
      );
    }

    // Only delete events if rebalance was successful
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
        message: `Successfully cleared ${result.count} event(s) and triggered rebalance`,
        task_id: rebalanceData.task_id,
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
        success: false,
        error: error instanceof Error ? error.message : "Internal server error",
        message: error instanceof Error ? error.message : "Internal server error",
      }),
      {
        status: 500,
        headers: { "content-type": "application/json" },
      }
    );
  }
}

