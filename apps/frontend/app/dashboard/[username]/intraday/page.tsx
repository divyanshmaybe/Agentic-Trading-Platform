"use client"

import { useState, useEffect } from "react"
import { useParams } from "next/navigation"
import { Loader2, Play, RotateCcw, Zap, ZapOff } from "lucide-react"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { IntradayNotifications, IntradayTradesTable } from "@/components/intraday"
import { PortfolioSnapshots } from "@/components/portfolio/PortfolioSnapshots"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/useAuth"
import { AgentOverview } from "@/components/agent"
import { useAgentDashboard } from "@/hooks/useAgentDashboard"
import { resetDatabase } from "@/lib/admin"
import { getDemoModeStatus, setDemoModeStatus } from "@/lib/portfolio"

export default function IntradayCommandCenterPage() {
  const params = useParams()
  const username = params.username as string
  const [triggeringAgent, setTriggeringAgent] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [showResetConfirm, setShowResetConfirm] = useState(false)
  const [demoMode, setDemoMode] = useState(false)
  const [togglingDemoMode, setTogglingDemoMode] = useState(false)

  // SECURE: Get user data from server-validated token, NOT localStorage
  const { user: authUser, loading: authLoading } = useAuth()
  
  const { data: agentData, loading: agentLoading, isAllocating } = useAgentDashboard("high_risk")

  // Fetch current Demo Mode state on mount
  useEffect(() => {
    const fetchDemoMode = async () => {
      try {
        const res = await getDemoModeStatus()
        setDemoMode(res.demo_mode)
      } catch (err) {
        console.error("Failed to load demo mode status:", err)
      }
    }
    fetchDemoMode()
  }, [])

  // Handle toggling Demo Mode
  const handleToggleDemoMode = async () => {
    setTogglingDemoMode(true)
    try {
      const nextState = !demoMode
      const res = await setDemoModeStatus(nextState)
      setDemoMode(res.demo_mode)
    } catch (err) {
      console.error("Failed to toggle demo mode:", err)
      alert(err instanceof Error ? err.message : "Failed to change demo mode")
    } finally {
      setTogglingDemoMode(false)
    }
  }

  // Handle resetting database
  const handleResetDatabase = async () => {
    setResetting(true)
    try {
      const response = await resetDatabase()
      alert(response.message || "Portfolio and trade logs reset successfully!")
      setShowResetConfirm(false)
      window.location.reload()
    } catch (error) {
      console.error("Failed to reset portfolio database:", error)
      alert(error instanceof Error ? error.message : "Failed to reset portfolio database")
    } finally {
      setResetting(false)
    }
  }

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
            <div className="flex flex-wrap items-center gap-4">
              {/* Reset Button with confirmation UI */}
              {showResetConfirm ? (
                <div className="flex items-center gap-2 rounded-md border border-rose-500/30 bg-rose-500/5 p-1 px-2 text-xs">
                  <span className="text-rose-200/90 font-medium">Reset all data?</span>
                  <Button
                    size="sm"
                    onClick={handleResetDatabase}
                    disabled={resetting}
                    className="h-7 border border-rose-500/40 bg-rose-500/20 px-2.5 text-xs text-rose-100 hover:bg-rose-500/30"
                  >
                    {resetting ? (
                      <Loader2 className="size-3 animate-spin" />
                    ) : (
                      "Yes"
                    )}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setShowResetConfirm(false)}
                    disabled={resetting}
                    className="h-7 px-2.5 text-xs text-zinc-400 hover:text-zinc-200"
                  >
                    Cancel
                  </Button>
                </div>
              ) : (
                <Button
                  onClick={() => setShowResetConfirm(true)}
                  disabled={triggeringAgent || resetting}
                  className="border border-rose-500/40 bg-rose-500/20 text-rose-100 hover:bg-rose-500/30"
                >
                  <RotateCcw className="mr-2 size-4" />
                  Reset Portfolio
                </Button>
              )}

              {/* Dynamic Demo Mode Toggle Button */}
              <Button
                onClick={handleToggleDemoMode}
                disabled={togglingDemoMode || triggeringAgent || resetting}
                className={`transition-all duration-300 border ${
                  demoMode
                    ? "border-sky-500/40 bg-sky-500/20 text-sky-100 hover:bg-sky-500/30 shadow-[0_0_12px_rgba(14,165,233,0.15)]"
                    : "border-zinc-700 bg-zinc-800/40 text-zinc-400 hover:bg-zinc-800/80 hover:text-zinc-300"
                }`}
              >
                {togglingDemoMode ? (
                  <Loader2 className="mr-2 size-4 animate-spin" />
                ) : demoMode ? (
                  <Zap className="mr-2 size-4 fill-sky-300 text-sky-300 animate-pulse" />
                ) : (
                  <ZapOff className="mr-2 size-4" />
                )}
                {demoMode ? "Demo Mode: ON" : "Demo Mode: OFF"}
              </Button>

              {/* Trigger Agent Button */}
              <Button
                onClick={handleTriggerAgent}
                disabled={triggeringAgent || resetting}
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
            </div>
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
