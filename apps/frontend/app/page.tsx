"use client"
import { useEffect } from "react"
import { Header } from "@/components/layout/Header"
import { Footer } from "@/components/layout/Footer"
import { Hero } from "@/components/landing/Hero"
import { Features } from "@/components/landing/Features"
import { PerformanceChart } from "@/components/landing/PerformanceChart"
import { Testimonials } from "@/components/landing/Testimonials"
import { CTA } from "@/components/landing/CTA"

export default function Home() {
  useEffect(() => {
    document.title = "AgentInvest — AI-powered portfolio management"
  }, [])

  return (
    <>
      <Header />
      <main>
        <Hero />
        <Features />
        <PerformanceChart />
        <Testimonials />
        <CTA />
      </main>
      <Footer />
    </>
  )
}
