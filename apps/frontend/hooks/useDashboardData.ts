import { useEffect, useState, useRef } from "react"
import type { PortfolioSummary, StockItem } from "@/lib/dashboardTypes"
import { getPortfolio, getPortfolioDashboard, getPositions, fetchMarketCandles } from "@/lib/portfolio"
import type { Portfolio } from "@/lib/portfolio"

function isPortfolioNotFoundError(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  const message = error.message.toLowerCase()
  return (
    message.includes("404") ||
    message.includes("not found") ||
    message.includes("portfolio not found")
  )
}

const emptyPortfolioSummary: PortfolioSummary = {
  portfolioName: "No Portfolio",
  currentValue: 0,
  totalUnrealizedPnl: 0,
  totalPnl: 0,
  totalReturnPct: 0,
  investmentAmount: 0,
  availableCash: 0,
  changePct: 0,
  changeValue: 0,
  dailyPnL: 0,
  riskTolerance: "N/A",
  expectedReturn: 0,
  investmentHorizon: 0,
  liquidityNeeds: "N/A",
  allocation: [],
}

export function useDashboardData(allocations: { label: string; value: number }[]) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary>(emptyPortfolioSummary)
  const [stocks, setStocks] = useState<StockItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [portfolioNotFound, setPortfolioNotFound] = useState(false)
  const hasInitialDataRef = useRef(false)
  const allocationsRef = useRef(allocations)

  // Keep allocations ref up to date
  useEffect(() => {
    allocationsRef.current = allocations
    // Update allocations in portfolioSummary when allocations change (without re-fetching)
    if (hasInitialDataRef.current && portfolioSummary.portfolioName !== "No Portfolio") {
      setPortfolioSummary((prev) => ({
        ...prev,
        allocation: allocations,
      }))
    }
  }, [allocations, portfolioSummary.portfolioName])

  useEffect(() => {
    async function fetchStocksData(positionsData: any) {
      if (positionsData.items.length === 0) {
        setStocks([])
        return
      }

      const symbols = positionsData.items.map((pos: any) => pos.symbol)
      
      try {
        const candlesResponse = await fetchMarketCandles(symbols, "30d")
        
        const stockItems: StockItem[] = positionsData.items.map((pos: any) => {
          const currentPrice = parseFloat(pos.current_price)
          const avgBuyPrice = parseFloat(pos.average_buy_price)
          const changePct = ((currentPrice - avgBuyPrice) / avgBuyPrice) * 100
          
          const candles = candlesResponse.metadata?.candles?.[pos.symbol]
          let prices: number[]
          let pricesError = false
          
          if (candles && candles.length > 0) {
            const sevenDaysAgo = new Date()
            sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7)
            
            const filteredCandles = candles.filter((c: any) => {
              const candleDate = new Date(c.timestamp)
              return candleDate >= sevenDaysAgo
            })
            
            prices = filteredCandles.map((c: any) => parseFloat(c.close))
          } else {
            prices = []
            pricesError = true
          }
          
          return {
            symbol: pos.symbol,
            name: pos.symbol,
            changePct: changePct,
            prices: prices,
            pricesError: pricesError,
          }
        })
        
        setStocks(stockItems)
      } catch (err) {
        console.error("Error fetching candle data:", err)
        
        const stockItemsWithoutPrices: StockItem[] = positionsData.items.map((pos: any) => {
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
    }

    async function fetchDashboardData(isPolling = false) {
      try {
        // Only show loading on initial fetch, not on polls when data exists
        if (!isPolling || !hasInitialDataRef.current) {
          setLoading(true)
        }
        setError(null)
        setPortfolioNotFound(false)

        let dashboardData
        try {
          dashboardData = await getPortfolioDashboard()
        } catch (err) {
          if (isPortfolioNotFoundError(err)) {
            setPortfolioNotFound(true)
            setPortfolioSummary(emptyPortfolioSummary)
            setStocks([])
            setLoading(false)
            return
          }
          throw err
        }
        
        let portfolioData
        try {
          portfolioData = await getPortfolio()
          setPortfolio(portfolioData)
        } catch (err) {
          if (isPortfolioNotFoundError(err)) {
            setPortfolioNotFound(true)
            setPortfolioSummary(emptyPortfolioSummary)
            setStocks([])
            setLoading(false)
            return
          }
          throw err
        }

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
        
        const investmentAmount = parseFloat(dashboardData.investment_amount)
        const availableCash = parseFloat(dashboardData.available_cash)
        const totalRealizedPnL = parseFloat(dashboardData.total_realized_pnl)
        
        // NEW: Use backend-calculated metrics (GROUND TRUTH from snapshot_service formula)
        const currentValue = parseFloat(dashboardData.current_portfolio_value)
        const totalUnrealizedPnl = parseFloat(dashboardData.total_unrealized_pnl)
        const totalPnl = parseFloat(dashboardData.total_pnl)
        const totalReturnPct = parseFloat(dashboardData.total_return_pct)

        setPortfolioSummary({
          portfolioName: dashboardData.portfolio_name,
          // NEW: Backend-calculated values
          currentValue: currentValue,
          totalUnrealizedPnl: totalUnrealizedPnl,
          totalPnl: totalPnl,
          totalReturnPct: totalReturnPct,
          // Existing fields
          investmentAmount: investmentAmount,
          availableCash: availableCash,
          // Deprecated (kept for backward compatibility)
          changePct: totalReturnPct,  // Use totalReturnPct instead
          changeValue: totalPnl,  // Use totalPnl instead
          dailyPnL: totalRealizedPnL,  // Use totalPnl instead
          riskTolerance: portfolioData.risk_tolerance,
          expectedReturn: parseFloat(portfolioData.expected_return_target) * 100,
          investmentHorizon: portfolioData.investment_horizon_years,
          liquidityNeeds: portfolioData.liquidity_needs,
          allocation: allocationsRef.current,
        })
        
        await fetchStocksData(positionsData)
        
        // Mark that we have initial data (only set to true, never reset)
        hasInitialDataRef.current = true
        
      } catch (err) {
        console.error("Error fetching dashboard data:", err)
        
        if (isPortfolioNotFoundError(err)) {
          setPortfolioNotFound(true)
          setPortfolioSummary(emptyPortfolioSummary)
          setStocks([])
        } else {
          const errorMessage = err instanceof Error ? err.message : "Failed to load dashboard data"
          setError(errorMessage)
        }
      } finally {
        setLoading(false)
      }
    }

    // Initial fetch
    fetchDashboardData(false)

    // Poll every 10 seconds
    const pollInterval = setInterval(() => {
      fetchDashboardData(true)
    }, 10000)

    return () => {
      clearInterval(pollInterval)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // Only run once on mount, allocations are updated separately

  return { portfolio, portfolioSummary, stocks, loading, error, portfolioNotFound }
}

