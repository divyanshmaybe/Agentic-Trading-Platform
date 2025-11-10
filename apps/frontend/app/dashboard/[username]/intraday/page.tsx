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

      <Container className="max-w-10xl space-y-8 px-4 py-8 sm:px-6 lg:px-12 xl:px-16">
        <section className="space-y-3">
          <p className="text-xs uppercase tracking-[0.3em] text-white/45">Intraday Strategy Console</p>
          <h1 className="text-4xl font-semibold text-[#fafafa]">Intraday Trading Strategies</h1>
          <p className="max-w-2xl text-sm text-white/60">
            Monitor fast-moving positions, react to live signals, and keep your intraday book aligned with
            algorithmic alerts.
          </p>
        </section>

        <div className="grid grid-cols-1 gap-6">
          <LowRiskNotificationPanel />
        </div>
      </Container>
    </div>
  )
}
