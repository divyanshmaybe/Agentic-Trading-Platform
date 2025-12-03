"use client"

import { useEffect, useRef } from "react"
import { useParams } from "next/navigation"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { NotificationCard } from "@/components/dashboard/NotificationCard"
import { ErrorMessage } from "@/components/dashboard/ErrorMessage"
import { AllocationWarning } from "@/components/dashboard/AllocationWarning"
import { DashboardContent } from "@/components/dashboard/DashboardContent"
import { PortfolioSnapshots } from "@/components/portfolio/PortfolioSnapshots"
import { Container } from "@/components/shared/Container"
import { useAuth } from "@/hooks/useAuth"
import { useDashboardNotifications } from "@/components/hooks/useDashboardNotifications"
import { usePortfolioAllocations } from "@/hooks/usePortfolioAllocations"
import { useDashboardData } from "@/hooks/useDashboardData"
import { enableAITradingSubscription } from "@/lib/objectiveIntake"
import "@/lib/chart"

export default function DashboardPage() {
  const params = useParams()
  const username = params.username as string
  const { stockRecommendations, newsSentiments, dismiss } = useDashboardNotifications()
  const { user: authUser, loading: authLoading } = useAuth()
  
  const { allocations, allocationError } = usePortfolioAllocations()
  const { portfolioSummary, stocks, loading, error, portfolioNotFound } = useDashboardData(allocations)
  
  const subscriptionsEnabledRef = useRef(false)

  // Auto-subscribe to all agents when allocations are loaded
  useEffect(() => {
    async function autoSubscribeAgents() {
      if (
        allocations.length > 0 && 
        !allocationError && 
        !subscriptionsEnabledRef.current &&
        authUser
      ) {
        subscriptionsEnabledRef.current = true
        try {
          const result = await enableAITradingSubscription()
          if (result.success) {
            console.log("✅ AI trading agents auto-subscribed:", result.message)
          } else {
            console.warn("⚠️ Failed to auto-subscribe agents:", result.message)
            subscriptionsEnabledRef.current = false
          }
        } catch (err) {
          console.error("❌ Error auto-subscribing to agents:", err)
          subscriptionsEnabledRef.current = false
        }
      }
    }

    autoSubscribeAgents()
  }, [allocations, allocationError, authUser])

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

      <Container className="max-w-none space-y-6 px-4 py-8 sm:px-6 lg:px-12 xl:px-16">
        {error && <ErrorMessage title="Error loading dashboard" message={error} />}

        <main className="grid gap-6 lg:grid-cols-4 xl:grid-cols-5 items-stretch">
          <div className="flex flex-col max-h-screen h-screen overflow-hidden">
            <NotificationCard 
              notifications={stockRecommendations} 
              title="Live Notifications"
              description="Keep up with your AI"
              onDismiss={dismiss}
            />
          </div>

          <div className="flex flex-col gap-6 lg:col-span-2 xl:col-span-3 h-screen overflow-y-auto min-w-0 pr-4">
            <DashboardContent
              portfolioNotFound={portfolioNotFound}
              portfolioSummary={portfolioSummary}
              stocks={stocks}
              loading={loading}
              username={username}
            />
            <div className="shrink-0">
              <PortfolioSnapshots title="Portfolio Snapshot History" />
            </div>
          </div>

          <div className="flex flex-col max-h-screen h-screen overflow-hidden">
            <NotificationCard 
              notifications={newsSentiments} 
              title="Top Headlines"
              description="News sentiment analysis"
              onDismiss={dismiss}
            />
          </div>
        </main>
      </Container>
    </div>
  )
}
