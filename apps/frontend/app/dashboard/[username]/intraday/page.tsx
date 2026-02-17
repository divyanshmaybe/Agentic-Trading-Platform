"use client"

import { useState } from "react"
import { useParams } from "next/navigation"
import { Loader2, Play } from "lucide-react"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { IntradayNotifications, IntradayTradesTable } from "@/components/intraday"
import { PortfolioSnapshots } from "@/components/portfolio/PortfolioSnapshots"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/useAuth"
import { AgentOverview } from "@/components/agent"
import { useAgentDashboard } from "@/hooks/useAgentDashboard"

export default function IntradayCommandCenterPage() {
  const params = useParams()
  const username = params.username as string
  const [triggeringAgent, setTriggeringAgent] = useState(false)

  // SECURE: Get user data from server-validated token, NOT localStorage
  const { user: authUser, loading: authLoading } = useAuth()
  
  const { data: agentData, loading: agentLoading, isAllocating } = useAgentDashboard("high_risk")

  // Handle triggering high_risk agent
  const handleTriggerAgent = async () => {
    setTriggeringAgent(true)
    try {
      const authServerUrl = process.env.NEXT_PUBLIC_AUTH_BASE_URL 
        ? process.env.NEXT_PUBLIC_AUTH_BASE_URL.replace("/api/auth", "")
        : "http://localhost:4000"
      
      // Get auth token
      let token: string | null = null
      if (typeof window !== "undefined") {
        const match = document.cookie.match(/(^| )access_token=([^;]+)/)
        token = match ? match[2] : localStorage.getItem("access_token")
      }

      const headers: HeadersInit = {
        "Content-Type": "application/json",
      }
      if (token) {
        headers["Authorization"] = `Bearer ${token}`
      }

      const response = await fetch(`${authServerUrl}/api/user/subscriptions`, {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify({
          action: "subscribe",
          agent: "high_risk",
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.message || data.error || "Failed to trigger high_risk agent")
      }

      // Show success message or handle as needed
      alert("High-risk agent triggered successfully!")
    } catch (error) {
      console.error("Failed to trigger high_risk agent:", error)
      alert(error instanceof Error ? error.message : "Failed to trigger high_risk agent")
    } finally {
      setTriggeringAgent(false)
    }
  }

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
          action={
            <Button
              onClick={handleTriggerAgent}
              disabled={triggeringAgent}
              className="border border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
            >
              {triggeringAgent ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Triggering...
                </>
              ) : (
                <>
                  <Play className="mr-2 size-4" />
                  Trigger High-Risk Agent
                </>
              )}
            </Button>
          }
        />

        <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div>
            <AgentOverview data={agentData} loading={agentLoading} isAllocating={isAllocating} />
          </div>
          <div>
            <PortfolioSnapshots agentType="high_risk" title="Performance Chart" />
          </div>
        </section>

        <section>
          <IntradayTradesTable agentId={agentData?.agent_id} />
        </section>

        <section>
          <IntradayNotifications />
        </section>
      </Container>
    </div>
  )
}
