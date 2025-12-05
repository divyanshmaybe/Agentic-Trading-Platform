import { useMemo, useRef, useEffect, useState } from "react"
import { Pie } from "react-chartjs-2"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import type { PortfolioSummary } from "@/lib/dashboardTypes"
import { formatCurrency } from "@/lib/dashboardData"
import { cn } from "@/lib/utils"
import { AllocationLoadingState } from "@/components/shared/AllocationLoadingState"
import { getPositions, fetchQuotes } from "@/lib/portfolio"

import { allocationChartOptions, createAllocationChartData, pieDepthPlugin } from "./chartConfig"

type PortfolioOverviewCardProps = {
  summary: PortfolioSummary
  loading?: boolean
}

export function PortfolioOverviewCard({ summary, loading = false }: PortfolioOverviewCardProps) {
  const hasAllocations = summary.allocation && summary.allocation.length > 0
  const hasEverLoadedPortfolioRef = useRef(false)
  const [currentPortfolioValue, setCurrentPortfolioValue] = useState<number | null>(null)
  const [unrealizedPnl, setUnrealizedPnl] = useState<number | null>(null)
  const [valueLoading, setValueLoading] = useState(false)
  const [valueError, setValueError] = useState<string | null>(null)
  
  // Track if we've ever successfully loaded portfolio data - once true, never show "Balancing Portfolio" again
  useEffect(() => {
    // If we're not loading and we have portfolio data (even if allocations are empty), mark as loaded
    if (!loading && summary.portfolioName !== "No Portfolio") {
      hasEverLoadedPortfolioRef.current = true
    }
  }, [loading, summary.portfolioName])
  
  // Calculate current portfolio value by fetching positions and quotes
  useEffect(() => {
    // Reset state when summary changes
    setCurrentPortfolioValue(null)
    setUnrealizedPnl(null)
    setValueError(null)
    setValueLoading(false)

    if (loading || summary.portfolioName === "No Portfolio") {
      return
    }

    let isMounted = true
    let isInitialFetch = true

    const calculateCurrentValue = async () => {
      if (!isMounted) return
      
      // Only show loading state on initial fetch, not on subsequent polls
      if (isInitialFetch) {
        setValueLoading(true)
        isInitialFetch = false
      }
      setValueError(null)

      try {
        // Fetch all positions (API has max limit of 100, so we need to paginate)
        let allPositions: any[] = []
        let page = 1
        const limit = 100 // Maximum allowed by API
        let hasMore = true

        try {
          while (hasMore && isMounted) {
            const positionsResponse = await getPositions(page, limit)
            
            if (!positionsResponse || !positionsResponse.items) {
              hasMore = false
              break
            }

            allPositions = [...allPositions, ...positionsResponse.items]

            // Check if there are more pages
            const totalPages = Math.ceil(positionsResponse.total / limit)
            hasMore = page < totalPages && positionsResponse.items.length === limit
            page++
          }
        } catch (positionsError) {
          // Handle 404 or other errors gracefully - just use available cash
          if (isMounted) {
            const errorMessage = positionsError instanceof Error ? positionsError.message : String(positionsError)
            // If it's a 404 or "not found" error, silently fall back to cash
            if (errorMessage.includes("404") || errorMessage.includes("not found") || errorMessage.includes("Not Found")) {
              setCurrentPortfolioValue(summary.availableCash)
              setValueLoading(false)
              return
            }
            // For other errors, log but still try to continue with available cash
            console.warn("Error fetching positions, using available cash only:", errorMessage)
            setCurrentPortfolioValue(summary.availableCash)
            setValueLoading(false)
            return
          }
          return
        }
        
        if (!isMounted) return

        if (allPositions.length === 0) {
          // No positions, current value is just available cash
          if (isMounted) {
            setCurrentPortfolioValue(summary.availableCash)
            setUnrealizedPnl(0)
            setValueLoading(false)
          }
          return
        }

        // Extract unique symbols from all positions
        const symbols = [...new Set(allPositions.map((pos) => pos.symbol).filter(Boolean))]
        
        // Skip if no valid symbols
        if (symbols.length === 0) {
          if (isMounted) {
            setCurrentPortfolioValue(summary.availableCash)
            setValueLoading(false)
          }
          return
        }
        
        // Fetch quotes for all symbols
        let quotesResponse
        try {
          quotesResponse = await fetchQuotes(symbols)
        } catch (fetchError) {
          // If quotes fail, we can still calculate with available cash
          console.warn("Error fetching quotes, using available cash only:", fetchError)
          if (isMounted) {
            setCurrentPortfolioValue(summary.availableCash)
            setValueLoading(false)
          }
          return
        }
        
        if (!quotesResponse || !quotesResponse.data) {
          // Invalid response, fall back to available cash
          if (isMounted) {
            setCurrentPortfolioValue(summary.availableCash)
            setValueLoading(false)
          }
          return
        }
        
        if (!isMounted) return
        
        // Check if we have missing quotes
        if (quotesResponse.missing && quotesResponse.missing.length > 0) {
          setValueError(`Missing quotes for: ${quotesResponse.missing.join(", ")}`)
        }

        // Create a map of symbol to price
        const priceMap = new Map<string, number>()
        if (quotesResponse.data) {
          quotesResponse.data.forEach((quote) => {
            if (quote && quote.symbol && quote.price) {
              priceMap.set(quote.symbol, parseFloat(quote.price))
            }
          })
        }

        // Calculate unrealized PnL from open positions
        let totalUnrealizedPnl = 0
        let hasMissingPrices = false

        for (const position of allPositions) {
          if (!position || !position.symbol) continue
          
          const currentPrice = priceMap.get(position.symbol)
          
          if (currentPrice === undefined || isNaN(currentPrice)) {
            hasMissingPrices = true
            continue // Skip positions without quotes
          }

          const quantity = position.quantity || 0
          const avgBuyPrice = parseFloat(position.average_buy_price || "0")
          
          if (quantity === 0 || isNaN(avgBuyPrice)) {
            continue
          }

          // Calculate unrealized PnL for this position
          const positionType = (position.position_type || "LONG").toUpperCase()
          let positionPnl: number
          
          if (positionType === "SHORT") {
            // SHORT: (average_buy_price - current_price) × quantity
            positionPnl = (avgBuyPrice - currentPrice) * quantity
          } else {
            // LONG: (current_price - average_buy_price) × quantity
            positionPnl = (currentPrice - avgBuyPrice) * quantity
          }
          
          totalUnrealizedPnl += positionPnl
        }

        if (hasMissingPrices && (!quotesResponse.missing || quotesResponse.missing.length === 0)) {
          setValueError("Some quotes are missing")
        }

        if (isMounted) {
          // Current Value = investment_amount + (realized_pnl + unrealized_pnl)
          // For main portfolio, realized PnL is embedded in summary.changeValue
          // changeValue represents total PnL (realized + unrealized from backend perspective)
          // But we calculate fresh unrealized PnL from current prices
          // So: Current Value = investment amount + all PnL changes
          const totalValue = summary.investmentAmount + summary.changeValue + (totalUnrealizedPnl - summary.changeValue)
          
          // Simplified: Since we're calculating unrealized PnL fresh, use it directly
          // Current Value = available_cash + (money_in_positions + unrealized_pnl_on_positions)
          // = available_cash + cost_basis + unrealized_pnl
          // = investment_amount + unrealized_pnl (since investment_amount = available_cash + cost_basis of positions)
          
          // Actually, the cleanest formula:
          // Current Value = Investment Amount + Total PnL
          // Where Total PnL includes both realized (from summary) and unrealized (calculated)
          // But summary doesn't give us realized PnL separately, so we use:
          const currentValue = summary.investmentAmount + totalUnrealizedPnl
          
          setCurrentPortfolioValue(currentValue)
          setUnrealizedPnl(totalUnrealizedPnl)
        }
      } catch (error) {
        console.error("Error calculating current portfolio value:", error)
        if (isMounted) {
          // Extract error message properly
          let errorMessage = "Failed to calculate portfolio value"
          if (error instanceof Error) {
            errorMessage = error.message
          } else if (typeof error === "string") {
            errorMessage = error
          } else if (error && typeof error === "object") {
            // Try to extract message from error object
            const errObj = error as Record<string, unknown>
            errorMessage = 
              (errObj.message as string) ||
              (errObj.error as string) ||
              (errObj.detail as string) ||
              JSON.stringify(error)
          }
          
          // If it's a 404 or not found error, just use available cash without showing error
          if (errorMessage.includes("404") || errorMessage.includes("not found") || errorMessage.includes("Not Found")) {
            setCurrentPortfolioValue(summary.availableCash)
            setValueError(null)
          } else {
            setValueError(errorMessage)
            // Still show available cash as fallback
            setCurrentPortfolioValue(summary.availableCash)
          }
        }
      } finally {
        if (isMounted) {
          setValueLoading(false)
        }
      }
    }

    // Calculate immediately
    calculateCurrentValue()

    // Set up polling to recalculate every 10 seconds
    const intervalId = setInterval(() => {
      if (isMounted) {
        calculateCurrentValue()
      }
    }, 10000) // 10 seconds

    return () => {
      isMounted = false
      clearInterval(intervalId)
    }
  }, [summary.availableCash, summary.portfolioName, loading])
  
  // Only show "Balancing Portfolio" if we've never loaded portfolio data and we're not currently loading
  const shouldShowBalancing = !hasEverLoadedPortfolioRef.current && !loading && !hasAllocations
  const allocationChart = useMemo(() => createAllocationChartData(summary.allocation), [summary.allocation])
  const formatted = useMemo(() => {
    // Use current portfolio value if available, otherwise fall back to totalValue from backend
    const displayValue = currentPortfolioValue !== null ? currentPortfolioValue : summary.totalValue

    // Calculate total PnL: realized PnL (from backend) + unrealized PnL (from positions)
    const realizedPnL = summary.changeValue // This is realized PnL from backend
    const totalPnL = unrealizedPnl !== null ? realizedPnL + unrealizedPnl : realizedPnL
    const changePositive = totalPnL >= 0
    
    // Calculate percentage based on initial investment
    const totalPnLPct = summary.investmentAmount > 0 
      ? (totalPnL / summary.investmentAmount) * 100 
      : 0

    return {
      totalValue: formatCurrency(summary.totalValue),
      investmentAmount: formatCurrency(summary.investmentAmount),
      availableCash: formatCurrency(summary.availableCash),
      currentPortfolioValue: formatCurrency(displayValue),
      realizedPnL: realizedPnL,
      realizedPnLFormatted: formatCurrency(realizedPnL),
      unrealizedPnL: unrealizedPnl,
      unrealizedPnLFormatted: unrealizedPnl !== null ? formatCurrency(unrealizedPnl) : null,
      totalPnL: Math.abs(totalPnL),
      totalPnLFormatted: formatCurrency(Math.abs(totalPnL)),
      totalPnLPct: Math.abs(totalPnLPct).toFixed(2),
      changeValue: Math.abs(summary.changeValue).toLocaleString("en-IN"),
      changePrefix: changePositive ? "+" : "-",
      changePctPrefix: totalPnL > 0 ? "+" : totalPnL < 0 ? "-" : "",
      riskTolerance: summary.riskTolerance.charAt(0).toUpperCase() + summary.riskTolerance.slice(1),
    }
  }, [summary, currentPortfolioValue, unrealizedPnl])

  return (
    <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur">
      <CardHeader className="gap-2">
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Portfolio Overview
        </CardDescription>
        <CardTitle className="h-title text-2xl text-[#fafafa]">
          {loading || valueLoading ? (
            <div className="h-8 w-48 animate-pulse rounded bg-white/10" />
          ) : valueError ? (
            <span className="text-sm text-rose-300" title={valueError}>
              {formatted.currentPortfolioValue} (Error)
            </span>
          ) : (
            formatted.currentPortfolioValue
          )}
        </CardTitle>

      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div className="grid gap-4">
          <div className="grid grid-cols-1 gap-4 text-sm text-white/70 sm:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Initial Investment</span>
              {loading ? (
                <div className="mt-2 h-6 w-24 animate-pulse rounded bg-white/10" />
              ) : (
                <p className="mt-2 text-lg font-semibold text-[#fafafa]">
                  {formatted.investmentAmount}
                </p>
              )}
            </div>
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Total P&L</span>
              {loading || valueLoading ? (
                <div className="mt-2 h-6 w-32 animate-pulse rounded bg-white/10" />
              ) : (
                <p
                  className={cn(
                    "mt-2 text-lg font-semibold",
                    formatted.changePrefix === "+" ? "text-[#22c55e]" : "text-[#ef4444]",
                  )}
                >
                  {formatted.changePctPrefix}
                  {formatted.totalPnLPct}% ({formatted.changePrefix}₹
                  {formatted.totalPnLFormatted})
                </p>
              )}
            </div>
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Realized P&L</span>
              {loading ? (
                <div className="mt-2 h-6 w-24 animate-pulse rounded bg-white/10" />
              ) : (
                <p className={cn(
                  "mt-2 text-lg font-semibold",
                  formatted.realizedPnL >= 0 ? "text-[#22c55e]" : "text-[#ef4444]",
                )}>
                  {formatted.realizedPnLFormatted}
                </p>
              )}
            </div>
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Unrealized P&L</span>
              {loading || valueLoading ? (
                <div className="mt-2 h-6 w-24 animate-pulse rounded bg-white/10" />
              ) : formatted.unrealizedPnL !== null ? (
                <p className={cn(
                  "mt-2 text-lg font-semibold",
                  formatted.unrealizedPnL >= 0 ? "text-[#22c55e]" : "text-[#ef4444]",
                )}>
                  {formatted.unrealizedPnLFormatted}
                </p>
              ) : (
                <p className="mt-2 text-lg font-semibold text-white/50">—</p>
              )}
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/8 p-4 text-sm text-white/70">
            <span className="text-xs uppercase tracking-[0.3em] text-white/45">Portfolio Details</span>
            {loading ? (
              <div className="mt-3 space-y-2">
                <div className="h-4 w-full animate-pulse rounded bg-white/10" />
                <div className="h-4 w-3/4 animate-pulse rounded bg-white/10" />
                <div className="h-4 w-5/6 animate-pulse rounded bg-white/10" />
              </div>
            ) : (
              <div className="mt-3 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <span className="text-white/60">Portfolio Name</span>
                  <span className="font-semibold text-[#fafafa]">{summary.portfolioName}</span>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <span className="text-white/60">Risk Tolerance</span>
                  <span className="font-semibold text-[#fafafa]">{formatted.riskTolerance}</span>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <span className="text-white/60">Expected Return</span>
                  <span className="font-semibold text-[#fafafa]">{summary.expectedReturn.toFixed(1)}%</span>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <span className="text-white/60">Investment Horizon</span>
                  <span className="font-semibold text-[#fafafa]">
                    {summary.investmentHorizon} {summary.investmentHorizon === 1 ? "year" : "years"}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center justify-center">
          {loading ? (
            <div className="w-full max-w-xs">
              <div className="h-64 w-64 animate-pulse rounded-full bg-white/10" />
            </div>
          ) : shouldShowBalancing ? (
            <AllocationLoadingState
              title="Balancing Portfolio"
              description="We're currently balancing your investments between long-term, intraday, and algorithmic trading strategies."
              steps={[
                "Analyzing risk profile...",
                "Optimizing allocations...",
                "Configuring strategies...",
              ]}
              className="w-full"
            />
          ) : hasAllocations ? (
            <div className="w-full max-w-xs">
              <Pie data={allocationChart} options={allocationChartOptions} plugins={[pieDepthPlugin]} />
            </div>
          ) : (
            // If we've had allocations before but they're empty now, show empty state instead of "Balancing Portfolio"
            <div className="w-full max-w-xs flex items-center justify-center">
              <div className="text-white/50 text-sm">No allocations available</div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

