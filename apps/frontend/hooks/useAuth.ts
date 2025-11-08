import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export interface AuthUser {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  role: "admin" | "staff" | "viewer";
  organizationId: string;
  username: string;
}

/**
 * SECURE hook to get current authenticated user
 * Fetches user data from server which validates the JWT cookie
 * NEVER trusts localStorage - all data comes from server-validated token
 */
export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    async function fetchUser() {
      try {
        setLoading(true);
        setError(null);

        // Call our secure API route that validates the cookie server-side
        const response = await fetch("/api/auth/me", {
          credentials: "include", // Include cookies
        });

        if (!response.ok) {
          if (response.status === 401) {
            // Not authenticated - redirect to login
            router.push("/login");
            return;
          }
          throw new Error("Failed to fetch user data");
        }

        const data = await response.json();
        setUser(data.user);
      } catch (err) {
        console.error("Error fetching user:", err);
        setError(err instanceof Error ? err.message : "Failed to load user");
      } finally {
        setLoading(false);
      }
    }

    fetchUser();
  }, [router]);

  return { user, loading, error };
}

