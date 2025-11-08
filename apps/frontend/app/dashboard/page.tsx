"use client"

import { useEffect, useState } from "react"
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

import { notificationItems, newsFeedItems, portfolioSummary as mockPortfolioSummary, stocks as mockStocks } from "./data"
import type { PortfolioSummary, StockItem } from "@/lib/dashboardTypes"
import { getPortfolio, getPositions, fetchQuotes } from "@/lib/portfolio"
import type { Portfolio, Position } from "@/lib/portfolio"

const playfair = Playfair_Display({ subsets: ["latin"], weight: ["400", "500", "600", "700"] })

export default function DashboardPage() {
  const activeNotifications = useRotatingList(notificationItems, 5500, 3)
  const activeNews = useRotatingList(newsFeedItems, 6000, 3)

  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary>(mockPortfolioSummary)
  const [stocks, setStocks] = useState<StockItem[]>(mockStocks)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function fetchDashboardData() {
      try {
        setLoading(true)
        setError(null)

        // Fetch portfolio data
        const portfolioData = await getPortfolio()
        setPortfolio(portfolioData)

        // Fetch positions
        const positionsData = await getPositions(1, 10)
        
        // Calculate portfolio summary (always update with API data)
        const totalValue = parseFloat(portfolioData.current_value)
        const investmentAmount = parseFloat(portfolioData.investment_amount)
        
        // Calculate total P&L from positions
        const totalPnL = positionsData.items.reduce(
          (sum, pos) => sum + parseFloat(pos.pnl),
          0
        )
        
        // Calculate change percentage
        const changePct = investmentAmount > 0 
          ? ((totalValue - investmentAmount) / investmentAmount) * 100 
          : 0
        
        // Keep the mock allocation for the pie chart as requested
        const allocation = [
          { label: "Alpha", value: 45 },
          { label: "Low-Risk", value: 32 },
          { label: "High-Risk", value: 23 },
        ]

        setPortfolioSummary({
          portfolioName: portfolioData.portfolio_name,
          totalValue: totalValue,
          investmentAmount: investmentAmount,
          changePct: changePct,
          changeValue: totalValue - investmentAmount,
          dailyPnL: totalPnL,
          riskTolerance: portfolioData.risk_tolerance,
          expectedReturn: parseFloat(portfolioData.expected_return_target) * 100, // Convert to percentage
          investmentHorizon: portfolioData.investment_horizon_years,
          liquidityNeeds: portfolioData.liquidity_needs,
          allocation: allocation,
        })
        
        if (positionsData.items.length > 0) {
          // Transform positions to stock items
          const stockItems: StockItem[] = positionsData.items.map((pos) => {
            const currentPrice = parseFloat(pos.current_price)
            const pnlPct = parseFloat(pos.pnl_percentage)
            
            // Generate simple price history (last 7 data points)
            // In production, you'd fetch historical data
            const basePrice = currentPrice / (1 + pnlPct / 100)
            const prices = generatePriceHistory(basePrice, currentPrice, 7)
            
            return {
              symbol: pos.symbol,
              name: pos.symbol, // Using symbol as name for now
              changePct: pnlPct,
              prices: prices,
            }
          })
          
          setStocks(stockItems)
        } else {
          // Clear stocks if no positions
          setStocks([])
        }
        
      } catch (err) {
        console.error("Error fetching dashboard data:", err)
        setError(err instanceof Error ? err.message : "Failed to load dashboard data")
        // Keep mock data on error
      } finally {
        setLoading(false)
      }
    }

    fetchDashboardData()
  }, [])

  // Generate simple price history for sparkline
  function generatePriceHistory(startPrice: number, endPrice: number, points: number): number[] {
    const prices: number[] = []
    const diff = endPrice - startPrice
    const step = diff / (points - 1)
    
    for (let i = 0; i < points; i++) {
      // Add some random variation for realistic sparkline
      const basePrice = startPrice + step * i
      const variation = basePrice * (Math.random() * 0.02 - 0.01) // ±1% variation
      prices.push(parseFloat((basePrice + variation).toFixed(2)))
    }
    
    // Ensure last price matches current price
    prices[points - 1] = endPrice
    
    return prices
  }

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

        {error && (
          <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-400">
            <p className="font-semibold">Error loading dashboard</p>
            <p>{error}</p>
          </div>
        )}

        <main className="grid h-[calc(40vh-12rem)] gap-6 lg:grid-cols-[1fr_1.6fr_1fr]">
          <NotificationCard notifications={activeNotifications} />

          <div className="flex flex-col gap-6">
            <PortfolioOverviewCard summary={portfolioSummary} loading={loading} />
            <StocksWatchlistCard stocks={stocks} loading={loading} />
          </div>

          <NewsFeedCard news={activeNews} />
        </main>
      </Container>
    </div>
  )
}
