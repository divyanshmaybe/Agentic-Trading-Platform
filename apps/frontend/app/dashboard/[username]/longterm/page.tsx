"use client"

import { useParams } from "next/navigation"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { useAuth } from "@/hooks/useAuth"

export default function HighRiskPage() {
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
          <h1 className="text-3xl font-bold">Long-Term Trading Strategies</h1>
          <p className="text-sm text-white/60">
            Monitor your high-risk positions and aggressive strategies.
          </p>
        </section>

        <div className="rounded-lg border border-white/10 bg-black/40 p-8">
          <p className="text-center text-white/50">Coming soon...</p>
        </div>
      </Container>
    </div>
  )
}

