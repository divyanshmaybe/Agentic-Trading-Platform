"use client"

import { useParams } from "next/navigation"
import { AlphaStats, TradeTable } from "@/components/alpha"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { IntradayNotifications } from "@/components/intraday"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { useAuth } from "@/hooks/useAuth"

export default function IntradayCommandCenterPage() {
  const params = useParams()
  const username = params.username as string

  // SECURE: Get user data from server-validated token, NOT localStorage
  const { user: authUser, loading: authLoading } = useAuth()

  // Show loading state while auth is being verified
  if (authLoading || !authUser) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0c0c0c] text-[#fafafa]">
        <div className="text-white/60">Loading...</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
      <DashboardHeader userName={authUser.firstName} username={username} userRole={authUser.role} />
      <Container className="max-w-10xl space-y-8 px-4 py-10 sm:px-6 lg:px-12 xl:px-16">
        <PageHeading
          tagline="Intraday Strategy Console"
          title="Intraday Command Center"
        />

        <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <AlphaStats />
          <TradeTable />
        </section>

        <section>
          <IntradayNotifications />
        </section>
      </Container>
    </div>
  )
}
