"use client"

import { useParams } from "next/navigation"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
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
        <PageHeading
          title="Long-Term Trading Strategies"
          tagline="Monitor your high-risk positions and aggressive strategies."
        />

        <div className="rounded-lg border border-white/10 bg-black/40 p-8">
          <p className="text-center text-white/50">Coming soon...</p>
        </div>
      </Container>
    </div>
  )
}

