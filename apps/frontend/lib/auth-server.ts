import { cookies } from "next/headers";

export interface AuthUser {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  role: "admin" | "staff" | "viewer";
  organizationId: string;
  username: string;
}

const AUTH_BASE_URL =
  process.env.AUTH_SERVER_URL || "http://localhost:4000";

/**
 * Validate token and get user data from auth service
 */
async function validateToken(
  token: string
): Promise<{ valid: boolean; user?: AuthUser; error?: string }> {
  try {
    if (!token || token.trim() === "") {
      return { valid: false, error: "Token is empty" };
    }

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
      return { valid: false, error: "Invalid token" };
    }

    const data = await response.json();

    if (data && data.user) {
      return { valid: true, user: data.user };
    }

    return { valid: false, error: "Invalid token response" };
  } catch (error: any) {
    console.error("Token validation error:", error.message);
    return { valid: false, error: "Token validation failed" };
  }
}

/**
 * Get current authenticated user from cookies
 * Returns null if not authenticated
 */
export async function getCurrentUser(): Promise<AuthUser | null> {
  try {
    const cookieStore = await cookies();
    const accessToken = cookieStore.get("access_token")?.value;

    if (!accessToken) {
      return null;
    }

    const validation = await validateToken(accessToken);

    if (!validation.valid || !validation.user) {
      return null;
    }

    return validation.user;
  } catch (error) {
    console.error("Error getting current user:", error);
    return null;
  }
}

/**
 * Check if user can access a specific username's dashboard
 * Users can access their own dashboard, admins can access any
 */
export async function canAccessDashboard(
  username: string
): Promise<{ allowed: boolean; user: AuthUser | null }> {
  const user = await getCurrentUser();

  if (!user) {
    return { allowed: false, user: null };
  }

  // Admins can access any dashboard
  if (user.role === "admin") {
    return { allowed: true, user };
  }

  // Users can only access their own dashboard
  if (user.username === username) {
    return { allowed: true, user };
  }

  return { allowed: false, user };
}

