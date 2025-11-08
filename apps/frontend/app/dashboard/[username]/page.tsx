"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { Playfair_Display } from "next/font/google"

import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { NotificationCard } from "@/components/dashboard/NotificationCard"
import { NewsFeedCard } from "@/components/dashboard/NewsFeedCard"
import { PortfolioOverviewCard } from "@/components/dashboard/PortfolioOverviewCard"
import { StocksWatchlistCard } from "@/components/dashboard/StocksWatchlistCard"
import { Container } from "@/components/shared/Container"
import { useRotatingList } from "@/hooks/useRotatingItem"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"
import "@/lib/chart"

import { notificationItems, newsFeedItems, portfolioSummary as mockPortfolioSummary, stocks as mockStocks } from "../data"
import type { PortfolioSummary, StockItem } from "@/lib/dashboardTypes"
import { getPortfolio, getPositions, fetchQuotes, fetchMarketCandles } from "@/lib/portfolio"
import type { Portfolio, Position } from "@/lib/portfolio"

const playfair = Playfair_Display({ subsets: ["latin"], weight: ["400", "500", "600", "700"] })

export default function DashboardPage() {
  const params = useParams()
  const username = params.username as string
  const activeNotifications = useRotatingList(notificationItems, 5500, 3)
  const activeNews = useRotatingList(newsFeedItems, 6000, 3)

  // SECURE: Get user data from server-validated token, NOT localStorage
  const { user: authUser, loading: authLoading } = useAuth()

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
          // Fetch 7-day candle data for all symbols (using 30d period for hourly intervals)
          const symbols = positionsData.items.map((pos) => pos.symbol)
          
          try {
            const candlesResponse = await fetchMarketCandles(symbols, "30d")
            
            // Transform positions to stock items with real candle data
            const stockItems: StockItem[] = positionsData.items.map((pos) => {
              const currentPrice = parseFloat(pos.current_price)
              const avgBuyPrice = parseFloat(pos.average_buy_price)
              
              // Calculate actual change percentage
              const changePct = ((currentPrice - avgBuyPrice) / avgBuyPrice) * 100
              
              // Extract close prices from candle data
              const candles = candlesResponse.metadata?.candles?.[pos.symbol]
              let prices: number[]
              let pricesError = false
              
              if (candles && candles.length > 0) {
                // Use all candles (close prices) - hourly intervals
                // Filter to last 7 days only (approximately 42 hourly candles)
                const sevenDaysAgo = new Date()
                sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7)
                
                const filteredCandles = candles.filter((c) => {
                  const candleDate = new Date(c.timestamp)
                  return candleDate >= sevenDaysAgo
                })
                
                prices = filteredCandles.map((c) => parseFloat(c.close))
              } else {
                // Fallback to generated history if no candles available
                prices = generatePriceHistory(avgBuyPrice, currentPrice, 7)
                pricesError = true
              }
              
              return {
                symbol: pos.symbol,
                name: pos.symbol, // Using symbol as name for now
                changePct: changePct,
                prices: prices,
                pricesError: pricesError,
              }
            })
            
            setStocks(stockItems)
          } catch (err) {
            console.error("Error fetching candle data:", err)
            
            // Fallback to generated history on error
            const stockItems: StockItem[] = positionsData.items.map((pos) => {
              const currentPrice = parseFloat(pos.current_price)
              const avgBuyPrice = parseFloat(pos.average_buy_price)
              const changePct = ((currentPrice - avgBuyPrice) / avgBuyPrice) * 100
              
              return {
                symbol: pos.symbol,
                name: pos.symbol,
                changePct: changePct,
                prices: generatePriceHistory(avgBuyPrice, currentPrice, 7),
                pricesError: true,
              }
            })
            
            setStocks(stockItems)
          }
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
    const totalChange = endPrice - startPrice
    
    for (let i = 0; i < points; i++) {
      const progress = i / (points - 1)
      const basePrice = startPrice + totalChange * progress

      // Add some realistic volatility (±1.5% random variation)
      const variation = basePrice * (Math.random() * 0.03 - 0.015)
      const price = basePrice + variation

      prices.push(parseFloat(price.toFixed(2)))
    }
    
    // Ensure last price is exactly the end price
    prices[points - 1] = endPrice
    
    return prices
  }

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
