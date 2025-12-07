import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const AUTH_BASE_URL = process.env.AUTH_SERVER_URL || "http://localhost:4000";

interface AuthUser {
  _id: string;
  email: string;
  firstName: string;
  lastName: string;
  role: "admin" | "staff" | "viewer";
  organizationId: string;
  username: string;
}

/**
 * Validate token with auth service
 */
async function validateToken(
  token: string
): Promise<{ valid: boolean; user?: AuthUser }> {
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
        body: JSON.stringify({ token }),
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

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Protect admin routes - require authentication AND admin role
  if (pathname.startsWith("/admin")) {
    const accessToken = request.cookies.get("access_token")?.value;

    if (!accessToken) {
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("redirect", pathname);
      return NextResponse.redirect(loginUrl);
    }

    const validation = await validateToken(accessToken);

    if (!validation.valid || !validation.user) {
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("redirect", pathname);
      return NextResponse.redirect(loginUrl);
    }

    // SECURITY: Only admins can access /admin routes
    if (validation.user.role !== "admin") {
      const forbiddenUrl = new URL("/403", request.url);
      return NextResponse.redirect(forbiddenUrl);
    }

    return NextResponse.next();
  }

  // Protect dashboard routes
  if (pathname.startsWith("/dashboard")) {
    // Get access token from cookie
    const accessToken = request.cookies.get("access_token")?.value;

    if (!accessToken) {
      // Redirect to login if no token
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("redirect", pathname);
      return NextResponse.redirect(loginUrl);
    }

    // Validate token
    const validation = await validateToken(accessToken);

    if (!validation.valid || !validation.user) {
      // Redirect to login if invalid token
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("redirect", pathname);
      return NextResponse.redirect(loginUrl);
    }

    // Check if accessing username-specific route
    const usernameMatch = pathname.match(/^\/dashboard\/([^\/]+)/);

    if (usernameMatch) {
      const requestedUsername = usernameMatch[1];
      const user = validation.user;

      // Admins can access any dashboard
      if (user.role === "admin") {
        return NextResponse.next();
      }

      // Non-admins can only access their own dashboard
      if (user.username !== requestedUsername) {
        // Redirect to their own dashboard
        const ownDashboardUrl = new URL(`/dashboard/${user.username}`, request.url);
        return NextResponse.redirect(ownDashboardUrl);
      }

      return NextResponse.next();
    }

    // If accessing base dashboard route, redirect to user's dashboard
    if (pathname === "/dashboard") {
      const user = validation.user;
      const dashboardUrl = new URL(`/dashboard/${user.username}`, request.url);
      return NextResponse.redirect(dashboardUrl);
    }

    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public files (images, etc.)
     */
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
