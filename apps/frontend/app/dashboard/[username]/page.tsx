"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import { Playfair_Display } from "next/font/google"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { NotificationCard } from "@/components/dashboard/NotificationCard"
import { NewsFeedCard } from "@/components/dashboard/NewsFeedCard"
import { PortfolioOverviewCard } from "@/components/dashboard/PortfolioOverviewCard"
import { StocksWatchlistCard } from "@/components/dashboard/StocksWatchlistCard"
import { Container } from "@/components/shared/Container"
import { useRotatingList } from "@/hooks/useRotatingItem"
import { useAuth } from "@/hooks/useAuth"
import "@/lib/chart"
import { notificationItems, portfolioSummary as mockPortfolioSummary, stocks as mockStocks } from "../data"
import type { PortfolioSummary, StockItem } from "@/lib/dashboardTypes"
import { getPortfolio, getPortfolioDashboard, getPositions, fetchMarketCandles, getPortfolioAllocations } from "@/lib/portfolio"
import type { Portfolio } from "@/lib/portfolio"
import { useLiveNewsFeed } from "@/hooks/useLiveNewsFeed"
import { Button } from "@/components/ui/button"

function isPortfolioNotFoundError(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  const message = error.message.toLowerCase()
  return (
    message.includes("404") ||
    message.includes("not found") ||
    message.includes("portfolio not found")
  )
}

export default function DashboardPage() {
  const params = useParams()
  const username = params.username as string
  const activeNotifications = useRotatingList(notificationItems, 5500, 3)
  const { news: liveNews, statusMessage: newsStatusMessage } = useLiveNewsFeed()

  // SECURE: Get user data from server-validated token, NOT localStorage
  const { user: authUser, loading: authLoading } = useAuth()

  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary>(mockPortfolioSummary)
  const [stocks, setStocks] = useState<StockItem[]>(mockStocks)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [portfolioNotFound, setPortfolioNotFound] = useState(false)
  const [allocationError, setAllocationError] = useState(false)

  useEffect(() => {
    async function fetchDashboardData() {
      try {
        setLoading(true)
        setError(null)
        setPortfolioNotFound(false)
        setAllocationError(false)

        // Fetch dashboard data (aggregated portfolio stats)
        let dashboardData
        try {
          dashboardData = await getPortfolioDashboard()
        } catch (err) {
          if (isPortfolioNotFoundError(err)) {
            setPortfolioNotFound(true)
            setPortfolioSummary({
              portfolioName: "No Portfolio",
              totalValue: 0,
              investmentAmount: 0,
              changePct: 0,
              changeValue: 0,
              dailyPnL: 0,
              riskTolerance: "N/A",
              expectedReturn: 0,
              investmentHorizon: 0,
              liquidityNeeds: "N/A",
              allocation: [],
            })
            setStocks([])
            setLoading(false)
            return
          }
          throw err
        }
        
        // Fetch portfolio details for additional fields
        let portfolioData
        try {
          portfolioData = await getPortfolio()
          setPortfolio(portfolioData)
        } catch (err) {
          if (isPortfolioNotFoundError(err)) {
            setPortfolioNotFound(true)
            setPortfolioSummary({
              portfolioName: "No Portfolio",
              totalValue: 0,
              investmentAmount: 0,
              changePct: 0,
              changeValue: 0,
              dailyPnL: 0,
              riskTolerance: "N/A",
              expectedReturn: 0,
              investmentHorizon: 0,
              liquidityNeeds: "N/A",
              allocation: [],
            })
            setStocks([])
            setLoading(false)
            return
          }
          throw err
        }

        // Fetch positions for stocks watchlist
        let positionsData
        try {
          positionsData = await getPositions(1, 10)
        } catch (err) {
          if (isPortfolioNotFoundError(err)) {
            setStocks([])
            return
          }
          throw err
        }
        
        // Fetch allocations to build allocation chart
        let allocation: Array<{ label: string; value: number }> = []
        
        try {
          const allocationsData = await getPortfolioAllocations()
          if (allocationsData.items.length > 0) {
            // Transform allocations to chart format
            const filteredAllocations = allocationsData.items
              .filter(alloc => alloc.allocation_type !== "cashAvailable")

            // Map API allocation types to display labels
            const allocationTypeToLabel: Record<string, string> = {
              "low_risk": "Long-Term",
              "Low_Risk": "Long-Term",
              "low risk": "Long-Term",
              "Low Risk": "Long-Term",
              "high_risk": "Intraday",
              "High_Risk": "Intraday",
              "high risk": "Intraday",
              "High Risk": "Intraday",
              "alpha": "Algorithmic",
              "Alpha": "Algorithmic",
            }
            
            allocation = filteredAllocations.map((alloc, index) => {
              // Get display label from mapping, or fallback to formatted allocation type
              const formattedType = alloc.allocation_type.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())
              const label = allocationTypeToLabel[alloc.allocation_type] || 
                           allocationTypeToLabel[formattedType] || 
                           formattedType
              
              let value = parseFloat(alloc.current_weight) * 100
              
              // Round to integer for all items except the last one
              if (index < filteredAllocations.length - 1) {
                value = Math.round(value)
              } else {
                // Last item: ensure percentages add up to exactly 100% by adjusting
                const sumSoFar = filteredAllocations
                  .slice(0, index)
                  .reduce((sum, a) => sum + Math.round(parseFloat(a.current_weight) * 100), 0)
                value = 100 - sumSoFar
              }
              
              return { label, value }
            })
          }
        } catch (err) {
          console.error("Error fetching allocations:", err)
          setAllocationError(true)
        }
        
        // Calculate portfolio summary from dashboard data
        const totalValue = parseFloat(dashboardData.current_value)
        const investmentAmount = parseFloat(dashboardData.investment_amount)
        const realizedPnL = parseFloat(dashboardData.realized_pnl)
        
        // Calculate change percentage
        const changePct = investmentAmount > 0 
          ? ((totalValue - investmentAmount) / investmentAmount) * 100 
          : 0

        setPortfolioSummary({
          portfolioName: dashboardData.portfolio_name,
          totalValue: totalValue,
          investmentAmount: investmentAmount,
          changePct: changePct,
          changeValue: totalValue - investmentAmount,
          dailyPnL: realizedPnL,
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
                // No price data available
                prices = []
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
            
            // Create stock items without price history when candle fetch fails
            const stockItemsWithoutPrices: StockItem[] = positionsData.items.map((pos) => {
              const currentPrice = parseFloat(pos.current_price)
              const avgBuyPrice = parseFloat(pos.average_buy_price)
              const changePct = ((currentPrice - avgBuyPrice) / avgBuyPrice) * 100
              
              return {
                symbol: pos.symbol,
                name: pos.symbol,
                changePct: changePct,
                prices: [],
                pricesError: true,
              }
            })
            
            setStocks(stockItemsWithoutPrices)
          }
        } else {
          // Clear stocks if no positions
          setStocks([])
        }
        
      } catch (err) {
        console.error("Error fetching dashboard data:", err)
        
        if (isPortfolioNotFoundError(err)) {
          setPortfolioNotFound(true)
          setPortfolioSummary({
            portfolioName: "No Portfolio",
            totalValue: 0,
            investmentAmount: 0,
            changePct: 0,
            changeValue: 0,
            dailyPnL: 0,
            riskTolerance: "N/A",
            expectedReturn: 0,
            investmentHorizon: 0,
            liquidityNeeds: "N/A",
            allocation: [],
          })
          setStocks([])
        } else {
          const errorMessage = err instanceof Error ? err.message : "Failed to load dashboard data"
          setError(errorMessage)
        }
      } finally {
        setLoading(false)
      }
    }

    fetchDashboardData()
  }, [])

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

      <Container className="max-w-none space-y-6 px-4 py-8 sm:px-6 lg:px-12 xl:px-16">

        {error && (
          <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-400">
            <p className="font-semibold">Error loading dashboard</p>
            <p>{error}</p>
          </div>
        )}

        {allocationError && !portfolioNotFound && (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-400">
            <p className="font-semibold">Portfolio Allocation Unavailable</p>
            <p className="mt-1">
              We're currently balancing your investments between long-term, intraday, and algorithmic trading strategies based on your objectives. 
              Allocation details will be available once the portfolio setup is complete.
            </p>
          </div>
        )}

        <main className="grid gap-6 lg:grid-cols-4 xl:grid-cols-5">
          <div className="flex">
            <NotificationCard notifications={activeNotifications} />
          </div>

          <div className="flex flex-col gap-6 lg:col-span-2 xl:col-span-3">
            {portfolioNotFound ? (
              <div className="card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur p-8">
                <div className="flex flex-col items-center justify-center text-center space-y-4">
                  <h3 className="text-2xl font-semibold text-[#fafafa]">No Portfolio Found</h3>
                  <p className="text-white/60 max-w-md">
                    You don't have a portfolio set up yet. Set your investment objectives to create your portfolio and start trading.
                  </p>
                  <Button asChild className="mt-4 bg-gradient-to-r from-[#1E1E3F] to-[#2B6CB0] text-white hover:opacity-90">
                    <Link href={`/dashboard/${username}/objectives`}>
                      Set Investment Objectives
                    </Link>
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <PortfolioOverviewCard summary={portfolioSummary} loading={loading} />
                <StocksWatchlistCard stocks={stocks} loading={loading} />
              </>
            )}
          </div>

          <div className="flex">
            <NewsFeedCard news={liveNews} statusMessage={newsStatusMessage} />
          </div>
        </main>
      </Container>
    </div>
  )
}
