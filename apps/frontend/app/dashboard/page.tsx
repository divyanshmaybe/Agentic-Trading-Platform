"use client"

import { Playfair_Display } from "next/font/google"

import { NotificationCard } from "@/components/dashboard/NotificationCard"
import { NewsFeedCard } from "@/components/dashboard/NewsFeedCard"
import { PortfolioOverviewCard } from "@/components/dashboard/PortfolioOverviewCard"
import { StocksWatchlistCard } from "@/components/dashboard/StocksWatchlistCard"
import { Button } from "@/components/ui/button"
import { Container } from "@/components/shared/Container"
import { useRotatingList } from "@/hooks/useRotatingItem"
import { cn } from "@/lib/utils"
import "@/lib/chart"

import { notificationItems, newsFeedItems, portfolioSummary, stocks } from "./data"

const playfair = Playfair_Display({ subsets: ["latin"], weight: ["400", "500", "600", "700"] })

export default function DashboardPage() {
  const activeNotifications = useRotatingList(notificationItems, 5500, 3)
  const activeNews = useRotatingList(newsFeedItems, 6000, 3)

  return (
    <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
      <Container className="max-w-10xl space-y-6 py-8">
        <section className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-2">
            <span className={cn("text-3xl font-semibold", playfair.className)}>Hello Aayush</span>
            <p className="max-w-xl text-sm text-white/60">
              Your unified desk view: positions, signals, desk notifications, and macro feeds in one dark lane.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              className="neon-hover rounded-lg border border-white/15 bg-black/40 px-6 py-2 text-sm font-semibold text-[#fafafa] transition hover:-translate-y-0.5 hover:border-white/30 hover:bg-black/60"
            >
              Logout
            </Button>
          </div>
        </section>

        <main className="grid gap-6 lg:grid-cols-[1fr_1.6fr_1fr]">
          <div className="flex flex-col">
            <NotificationCard notifications={activeNotifications} />
          </div>

          <div className="flex flex-col gap-6">
            <PortfolioOverviewCard summary={portfolioSummary} />
            <StocksWatchlistCard stocks={stocks} />
          </div>

          <div className="flex flex-col">
            <NewsFeedCard news={activeNews} />
          </div>
        </main>
      </Container>
    </div>
  )
}
