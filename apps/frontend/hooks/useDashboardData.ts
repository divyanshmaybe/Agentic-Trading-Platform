import { useEffect, useState } from "react"
import type { PortfolioSummary, StockItem } from "@/lib/dashboardTypes"
import { getPortfolio, getPortfolioDashboard, getPositions, fetchMarketCandles } from "@/lib/portfolio"
import type { Portfolio } from "@/lib/portfolio"
import { portfolioSummary as mockPortfolioSummary, stocks as mockStocks } from "../app/dashboard/data"

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
  totalValue: 0,
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
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary>(mockPortfolioSummary)
  const [stocks, setStocks] = useState<StockItem[]>(mockStocks)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [portfolioNotFound, setPortfolioNotFound] = useState(false)

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

    async function fetchDashboardData() {
      try {
        setLoading(true)
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
        const totalValue = investmentAmount + totalRealizedPnL
        
        const changePct = investmentAmount > 0 
          ? (totalRealizedPnL / investmentAmount) * 100 
          : 0
        const changeValue = totalRealizedPnL

        setPortfolioSummary({
          portfolioName: dashboardData.portfolio_name,
          totalValue: totalValue,
          investmentAmount: investmentAmount,
          availableCash: availableCash,
          changePct: changePct,
          changeValue: changeValue,
          dailyPnL: totalRealizedPnL,
          riskTolerance: portfolioData.risk_tolerance,
          expectedReturn: parseFloat(portfolioData.expected_return_target) * 100,
          investmentHorizon: portfolioData.investment_horizon_years,
          liquidityNeeds: portfolioData.liquidity_needs,
          allocation: allocations,
        })
        
        await fetchStocksData(positionsData)
        
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

    fetchDashboardData()
  }, [allocations])

  return { portfolio, portfolioSummary, stocks, loading, error, portfolioNotFound }
}

