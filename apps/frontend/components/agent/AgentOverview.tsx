"use client"

import { useState, useEffect } from "react"
import { motion, type Variants } from "framer-motion"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { AgentDashboard } from "@/lib/types/agent"
import { formatCurrencyInteger, formatPercentageInteger, displayValue } from "@/lib/utils/formatters"
import { AllocationLoadingState } from "@/components/shared/AllocationLoadingState"
import { fetchQuotes } from "@/lib/portfolio"

const container: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: {
    opacity: 1,
    y: 0,
    transition: { staggerChildren: 0.08, duration: 0.4, ease: [0.37, 0, 0.63, 1] },
  },
}

const item: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0 },
}

interface AgentOverviewProps {
  data: AgentDashboard | null
  loading: boolean
  isAllocating?: boolean
}

export function AgentOverview({ data, loading, isAllocating = false }: AgentOverviewProps) {
  const [unrealizedPnl, setUnrealizedPnl] = useState<number | null>(null)
  const [currentValue, setCurrentValue] = useState<number | null>(null)
  const [quotesLoading, setQuotesLoading] = useState(false)
  const [quotesError, setQuotesError] = useState<string | null>(null)

  // Fetch quotes and calculate unrealized PnL + current value when positions data is available
  useEffect(() => {
    // Reset state when data changes
    setUnrealizedPnl(null)
    setCurrentValue(null)
    setQuotesError(null)
    setQuotesLoading(false)

    if (!data) {
      return
    }

    // Get available cash from allocation
    const availableCash = parseFloat(data.allocation?.available_cash || "0")

    if (!data.positions || data.positions.length === 0) {
      // No positions, current value is just available cash
      setCurrentValue(availableCash)
      setUnrealizedPnl(0)
      return
    }

    let isMounted = true
    let isInitialFetch = true

    const calculateMetrics = async () => {
      if (!isMounted) return
      
      // Only show loading state on initial fetch, not on subsequent polls
      if (isInitialFetch) {
        setQuotesLoading(true)
        isInitialFetch = false
      }
      setQuotesError(null)

      try {
        // Extract unique symbols from positions
        const symbols = [...new Set(data.positions.map((pos) => pos.symbol).filter(Boolean))]
        
        // Skip if no valid symbols
        if (symbols.length === 0) {
          if (isMounted) {
            setCurrentValue(availableCash)
            setUnrealizedPnl(0)
            setQuotesLoading(false)
          }
          return
        }
        
        // Fetch quotes for all symbols
        let quotesResponse
        try {
          quotesResponse = await fetchQuotes(symbols)
        } catch (fetchError) {
          console.error("Network error fetching quotes:", fetchError)
          throw fetchError // Re-throw to be caught by outer catch
        }
        
        if (!quotesResponse || !quotesResponse.data) {
          throw new Error("Invalid quotes response")
        }
        
        if (!isMounted) return
        
        // Check if we have missing quotes
        if (quotesResponse.missing && quotesResponse.missing.length > 0) {
          setQuotesError(`Missing quotes for: ${quotesResponse.missing.join(", ")}`)
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

        for (const position of data.positions) {
          if (!position || !position.symbol) continue
          
          const currentPrice = priceMap.get(position.symbol)
          
          if (currentPrice === undefined || isNaN(currentPrice)) {
            hasMissingPrices = true
            continue // Skip positions without quotes
          }

          const quantity = position.quantity || 0
          const averageBuyPrice = parseFloat(position.average_buy_price || "0")
          
          if (quantity === 0 || isNaN(averageBuyPrice)) {
            continue
          }

          const positionType = (position.position_type || "LONG").toUpperCase()

          // Calculate unrealized PnL for this position
          let positionPnl: number
          if (positionType === "SHORT") {
            // SHORT: (average_buy_price - current_price) × quantity
            positionPnl = (averageBuyPrice - currentPrice) * quantity
          } else {
            // LONG: (current_price - average_buy_price) × quantity
            positionPnl = (currentPrice - averageBuyPrice) * quantity
          }

          totalUnrealizedPnl += positionPnl
        }

        if (hasMissingPrices && (!quotesResponse.missing || quotesResponse.missing.length === 0)) {
          setQuotesError("Some quotes are missing")
        }

        if (isMounted) {
          // Current Value = Available Cash + Positions Value
          // Unrealized PnL = Σ((current_price - avg_buy_price) × quantity)
          // This matches backend calculation in snapshot_service.py
          
          // Calculate total position value
          let totalPositionValue = 0
          
          for (const position of data.positions) {
            if (!position || !position.symbol) continue
            
            const currentPrice = priceMap.get(position.symbol)
            if (currentPrice === undefined || isNaN(currentPrice)) continue
            
            const quantity = position.quantity || 0
            if (quantity === 0) continue
            
            totalPositionValue += currentPrice * quantity
          }
          
          // Current Value = Available Cash + Current Position Values
          const portfolioCurrentValue = availableCash + totalPositionValue
          
          setCurrentValue(portfolioCurrentValue)
          setUnrealizedPnl(totalUnrealizedPnl)
        }
      } catch (error) {
        console.error("Error fetching quotes:", error)
        if (isMounted) {
          setQuotesError(error instanceof Error ? error.message : "Failed to fetch market quotes")
          // Fallback to available cash only
          setCurrentValue(availableCash)
          setUnrealizedPnl(null)
        }
      } finally {
        if (isMounted) {
          setQuotesLoading(false)
        }
      }
    }

    // Calculate immediately
    calculateMetrics()

    // Set up polling to recalculate every 10 seconds
    const intervalId = setInterval(() => {
      if (isMounted) {
        calculateMetrics()
      }
    }, 10000) // 10 seconds

    return () => {
      isMounted = false
      clearInterval(intervalId)
    }
  }, [data])

  // Show allocating message when agents are being created
  if (isAllocating) {
    return (
      <AllocationLoadingState
        title="Allocating Your Portfolio"
        description="We're setting up your trading agents and allocating your portfolio. This usually takes a few moments."
        steps={[
          "Creating agent instances...",
          "Calculating optimal allocations...",
          "Initializing trading strategies...",
        ]}
        asCard
      />
    )
  }

  if (loading || !data) {
    return (
      <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
        <CardHeader>
          <CardTitle className="h-title text-xl text-[#fafafa]">Agent Overview</CardTitle>
          <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
            Loading agent data...
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div
                key={i}
                className="animate-pulse rounded-xl border border-white/10 bg-white/8 p-4"
              >
                <div className="h-3 w-20 rounded bg-white/20" />
                <div className="mt-2 h-7 w-32 rounded bg-white/20" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  const statusColor = {
    active: "bg-emerald-500/15 text-emerald-200",
    paused: "bg-amber-500/15 text-amber-200",
    stopped: "bg-rose-500/15 text-rose-200",
    error: "bg-red-500/15 text-red-200",
  }[data.status] || "bg-gray-500/15 text-gray-200"

  const pnlValue = parseFloat(data.realized_pnl || "0")
  const isPnlPositive = pnlValue >= 0
  
  // Calculate realized PnL percentage from allocation
  const allocatedAmount = parseFloat(data.allocation.allocated_amount || "0")
  const realizedPnLPercentage = allocatedAmount > 0 
    ? (pnlValue / allocatedAmount) * 100 
    : 0
  const isRealizedPnLPositive = realizedPnLPercentage >= 0

  return (
    <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="h-title text-xl text-[#fafafa]">{data.agent_name}</CardTitle>
          <span
            className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase ${statusColor}`}
          >
            {data.status}
          </span>
        </div>
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Agent Performance
        </CardDescription>
      </CardHeader>
      <CardContent className="flex-1">
        <motion.div
          className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
          variants={container}
          initial="hidden"
          animate="show"
        >
          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/5 p-4"
          >
            <p className="text-xs text-white/60">Current Value</p>
            {quotesLoading && currentValue === null ? (
              <p className="mt-1 text-lg font-semibold text-white/50">Loading...</p>
            ) : quotesError && currentValue === null ? (
              <p className="mt-1 text-sm font-semibold text-rose-300" title={quotesError}>
                Error
              </p>
            ) : currentValue !== null ? (
              <p className="mt-1 text-lg font-semibold text-[#fafafa]">
                {formatCurrencyInteger(currentValue)}
              </p>
            ) : (
              <p className="mt-1 text-lg font-semibold text-white/50">—</p>
            )}
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/5 p-4"
          >
            <p className="text-xs text-white/60">Realized PnL</p>
            <p className={`mt-1 text-lg font-semibold ${isPnlPositive ? "text-emerald-300" : "text-rose-300"}`}>
              {formatCurrencyInteger(data.realized_pnl)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/5 p-4"
          >
            <p className="text-xs text-white/60">Unrealized PnL</p>
            {quotesLoading ? (
              <p className="mt-1 text-lg font-semibold text-white/50">Loading...</p>
            ) : quotesError ? (
              <p className="mt-1 text-sm font-semibold text-rose-300" title={quotesError}>
                Error
              </p>
            ) : unrealizedPnl !== null ? (
              <p className={`mt-1 text-lg font-semibold ${unrealizedPnl >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                {formatCurrencyInteger(unrealizedPnl)}
              </p>
            ) : (
              <p className="mt-1 text-lg font-semibold text-white/50">—</p>
            )}
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/5 p-4"
          >
            <p className="text-xs text-white/60">Positions</p>
            <p className="mt-1 text-lg font-semibold text-[#fafafa]">{data.positions_count}</p>
          </motion.div>

          {/* <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Target Weight</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatWeight(data.allocation.target_weight)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
          >
            <p className="text-xs uppercase tracking-wide text-white/45">Current Weight</p>
            <p className="mt-2 text-2xl font-semibold text-[#fafafa]">
              {formatWeight(data.allocation.current_weight)}
            </p>
          </motion.div> */}

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/5 p-4"
          >
            <p className="text-xs text-white/60">Allocated Amount</p>
            <p className="mt-1 text-lg font-semibold text-[#fafafa]">
              {formatCurrencyInteger(data.allocation.allocated_amount)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/5 p-4"
          >
            <p className="text-xs text-white/60">Available Cash</p>
            <p className="mt-1 text-lg font-semibold text-[#fafafa]">
              {formatCurrencyInteger(data.allocation.available_cash)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/5 p-4"
          >
            <p className="text-xs text-white/60">Regime</p>
            <p className="mt-1 text-lg font-semibold text-[#fafafa]">
              {displayValue(data.allocation.regime).replace(/_/g, " ").toUpperCase()}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/5 p-4"
          >
            <p className="text-xs text-white/60">Realized PnL %</p>
            <p className={`mt-1 text-lg font-semibold ${isRealizedPnLPositive ? "text-emerald-300" : "text-rose-300"}`}>
              {realizedPnLPercentage >= 0 ? "+" : ""}{realizedPnLPercentage.toFixed(2)}%
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/5 p-4"
          >
            <p className="text-xs text-white/60">Drift %</p>
            <p className="mt-1 text-lg font-semibold text-[#fafafa]">
              {formatPercentageInteger(data.allocation.drift_percentage)}
            </p>
          </motion.div>

          <motion.div
            variants={item}
            className="rounded-xl border border-white/10 bg-white/5 p-4"
          >
            <p className="text-xs text-white/60">Rebalancing</p>
            <p className="mt-1 text-lg font-semibold">
              {data.allocation.requires_rebalancing ? (
                <span className="text-amber-300">Required</span>
              ) : (
                <span className="text-emerald-300">Not Required</span>
              )}
            </p>
          </motion.div>
        </motion.div>
      </CardContent>
    </Card>
  )
}