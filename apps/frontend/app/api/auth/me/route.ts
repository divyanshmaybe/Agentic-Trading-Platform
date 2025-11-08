import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const AUTH_BASE_URL = process.env.AUTH_SERVER_URL || "http://localhost:4000";

/**
 * GET /api/auth/me
 * Returns current authenticated user data by validating the access_token cookie
 * This is SECURE because it validates the token on the server
 */
export async function GET(request: NextRequest) {
  try {
    const cookieStore = await cookies();
    const accessToken = cookieStore.get("access_token")?.value;

    console.log("🔍 /api/auth/me - Checking authentication");
    console.log("📦 All cookies:", cookieStore.getAll().map(c => c.name));
    console.log("🎫 Access token found:", !!accessToken);

    if (!accessToken) {
      console.error("❌ No access_token cookie found");
      return NextResponse.json(
        { error: "Not authenticated - no access token" },
        { status: 401 }
      );
    }

    // Validate token with auth service
    console.log("🔗 Validating token with auth service:", AUTH_BASE_URL);
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

    console.log("📡 Auth service response status:", response.status);

    if (!response.ok) {
      const errorText = await response.text();
      console.error("❌ Token validation failed:", response.status, errorText);
      return NextResponse.json(
        { error: "Invalid or expired token" },
        { status: 401 }
      );
    }

    const data = await response.json();
    console.log("✅ Token validated successfully, user:", data.user?.email);

    if (!data.valid || !data.user) {
      console.error("❌ Invalid token response structure:", data);
      return NextResponse.json(
        { error: "Invalid token response" },
        { status: 401 }
      );
    }

    // Return user data (this is secure - validated by server)
    return NextResponse.json({
      user: {
        id: data.user._id,
        email: data.user.email,
        firstName: data.user.firstName,
        lastName: data.user.lastName,
        role: data.user.role,
        organizationId: data.user.organizationId,
        username: data.user.username,
      },
    });
  } catch (error) {
    console.error("Error fetching current user:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}

