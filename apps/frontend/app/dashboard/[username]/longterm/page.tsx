"use client"

import { useParams } from "next/navigation"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { useAuth } from "@/hooks/useAuth"
import { AgentOverview, AgentTradesTable } from "@/components/agent"
import { useAgentDashboard } from "@/hooks/useAgentDashboard"
import { useLowRiskEvents } from "@/components/hooks/useLowRiskEvents"

export default function LongTermPage() {
  const params = useParams()
  const username = params.username as string
  
  // SECURE: Get user data from server-validated token, NOT localStorage
  const { user: authUser, loading: authLoading } = useAuth()
  
  const { data: agentData, loading: agentLoading, isAllocating } = useAgentDashboard("low_risk")
  const { events, startStreaming, stopStreaming, streaming } = useLowRiskEvents()

  const handleRunPipeline = () => {
    startStreaming()
  }

  const handleStopPipeline = () => {
    stopStreaming()
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
          title="Long-Term Strategy Center"
          tagline="Monitor your low-risk positions and conservative strategies."
        />

        <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <AgentOverview data={agentData} loading={agentLoading} isAllocating={isAllocating} />
          <AgentTradesTable trades={agentData?.recent_trades ?? []} loading={agentLoading} />
        </section>

        {!agentLoading && !isAllocating && agentData !== null && (
          <div className="w-full space-y-6">
            <div className="w-full rounded-2xl border border-white/10 bg-white/5 p-10 flex items-center justify-center gap-4">
              <button
                className="px-8 py-4 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
                onClick={handleRunPipeline}
                disabled={streaming}
              >
                {streaming ? "Pipeline Running…" : "Run Pipeline"}
              </button>
              
              {streaming && (
                <button
                  className="px-8 py-4 rounded-xl bg-red-600 text-white font-semibold hover:bg-red-700 transition"
                  onClick={handleStopPipeline}
                >
                  Stop Pipeline
                </button>
              )}
            </div>

            {streaming && (
              <div className="w-full rounded-2xl border border-white/10 bg-white/5 p-6">
                <h3 className="text-lg font-semibold mb-4 text-white">Live Pipeline Events</h3>
                <div className="max-h-[600px] overflow-y-auto">
                  {events.length === 0 ? (
                    <div className="text-white/60 text-sm">Waiting for events...</div>
                  ) : (
                    <div className="space-y-4">
                      {events.map((event) => (
                        <div
                          key={event.id}
                          className="rounded-lg border border-white/10 bg-black/20 p-4"
                        >
                          <pre className="text-xs text-white/90 whitespace-pre-wrap wrap-break-word font-mono">
                            {JSON.stringify(event, null, 2)}
                          </pre>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </Container>
    </div>
  )
}
