"use client"

import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"

export default function AlphasPage() {
  return (
    <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
      <DashboardHeader userName="Aayush" />
      
      <Container className="max-w-10xl space-y-6 py-8">
        <section className="space-y-4">
          <h1 className="text-3xl font-bold">Alpha Strategies</h1>
          <p className="text-sm text-white/60">
            View and manage your alpha-generating strategies and positions.
          </p>
        </section>

        <div className="rounded-lg border border-white/10 bg-black/40 p-8">
          <p className="text-center text-white/50">Coming soon...</p>
        </div>
      </Container>
    </div>
  )
}

