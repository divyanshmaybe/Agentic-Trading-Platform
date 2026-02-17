import type { Metadata } from "next"
import { redirect } from "next/navigation";
import { getCurrentUser, canAccessDashboard } from "@/lib/auth-server";

export const metadata: Metadata = {
  title: "Dashboard",
}

interface DashboardLayoutProps {
  children: React.ReactNode;
  params: Promise<{ username: string }>;
}

export default async function DashboardLayout({
  children,
  params,
}: DashboardLayoutProps) {
  const { username } = await params;

  // Check if user can access this dashboard
  const { allowed, user } = await canAccessDashboard(username);

  if (!allowed) {
    // If not authenticated, redirect to login
    if (!user) {
      redirect(`/login?redirect=/dashboard/${username}`);
    }
    // If authenticated but not authorized, show 403
    redirect("/403");
  }

  return <>{children}</>;
}

