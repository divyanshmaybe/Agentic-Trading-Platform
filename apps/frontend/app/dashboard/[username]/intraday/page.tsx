"use client"

import { useParams } from "next/navigation"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { useAuth } from "@/hooks/useAuth"
import { LowRiskNotificationPanel } from "@/components/low-risk/LowRiskNotificationPanel"

export default function LowRiskPage() {
  const params = useParams()
  const username = params.username as string

  // SECURE: Get user data from server-validated token, NOT localStorage
  const { user: authUser, loading: authLoading } = useAuth()

  // Show loading state while auth is being verified
  if (authLoading || !authUser) {
    return (
      <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa] flex items-center justify-center">
        <div className="text-white/60">Loading...</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
      <DashboardHeader userName={authUser.firstName} username={username} userRole={authUser.role} />

      <Container className="max-w-10xl space-y-6 py-8">
        <section className="space-y-4">
          <h1 className="text-3xl font-bold">Intraday Trading Strategies</h1>
          <p className="text-sm text-white/60">
            Track your conservative investments and stable returns.
          </p>
        </section>

        <div className="grid grid-cols-1 gap-6">
          <LowRiskNotificationPanel />
        </div>
      </Container>
    </div>
  )
}
