"use client"

import { useState, useEffect, useCallback, useRef, useMemo } from "react"
import { motion } from "framer-motion"
import { ChevronLeft, ChevronRight, RefreshCw, TrendingUp, TrendingDown, ArrowRightLeft } from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import type { AgentTrade } from "@/lib/types/agent"
import { formatCurrency, formatCurrencyInteger, formatDuration } from "@/lib/utils/formatters"
import { getRecentTrades, fetchQuotes } from "@/lib/portfolio"

const rowVariants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.2 } },
}

const PAGE_SIZE_OPTIONS = [10, 25, 100] as const

// Trade pair - a completed round trip (buy + sell)
interface TradePair {
  symbol: string
  buyTrade: AgentTrade
  sellTrade: AgentTrade
  buyPrice: number
  sellPrice: number
  quantity: number
  pnl: number
  pnlPercent: number
  holdingTime: string
}

// Open position - only one side of the trade
interface OpenPosition {
  symbol: string
  trade: AgentTrade
  side: "BUY" | "SELL"
  price: number
  quantity: number
  currentPrice?: number
  unrealizedPnl?: number
  unrealizedPnlPercent?: number
}

interface AgentTradesTableProps {
  trades?: AgentTrade[]
  loading?: boolean
  agentType?: string
  agentId?: string
  mode?: "simple" | "advanced"
}

// =====================================================
// SIMPLE TABLE - Used for longterm and intraday pages
// =====================================================
function SimpleTradesTable({ trades, loading }: { trades: AgentTrade[]; loading: boolean }) {
  const [currentPrices, setCurrentPrices] = useState<Map<string, number>>(new Map())
  const [pricesLoading, setPricesLoading] = useState(false)

  // Fetch current prices for symbols in trades
  useEffect(() => {
    if (trades.length === 0) return

    const symbols = [...new Set(trades.map((t) => t.symbol).filter(Boolean))]
    if (symbols.length === 0) return

    const fetchPrices = async () => {
      setPricesLoading(true)
      try {
        const response = await fetchQuotes(symbols)
        if (response?.data) {
          const priceMap = new Map<string, number>()
          response.data.forEach((quote) => {
            if (quote?.symbol && quote?.price) {
              priceMap.set(quote.symbol, parseFloat(quote.price))
            }
          })
          setCurrentPrices(priceMap)
        }
      } catch (error) {
        console.error("Failed to fetch current prices:", error)
      } finally {
        setPricesLoading(false)
      }
    }

    fetchPrices()
    // Poll every 10 seconds
    const interval = setInterval(fetchPrices, 10000)
    return () => clearInterval(interval)
  }, [trades])

  if (loading) {
    return (
      <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
        <CardHeader>
          <CardTitle className="h-title text-xl text-[#fafafa]">Recent Trades</CardTitle>
          <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
            Loading trades...
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="animate-pulse rounded-xl border border-white/10 bg-white/8 p-4">
                <div className="h-4 w-full rounded bg-white/20" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  const formatTime = (dateString: string) => {
    try {
      return new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }).format(new Date(dateString))
    } catch {
      return dateString
    }
  }

  const getSideBadgeColor = (side: string) => {
    const sideLower = side.toLowerCase()
    if (sideLower === "buy") return "bg-emerald-500/15 text-emerald-200"
    if (sideLower === "sell") return "bg-rose-500/15 text-rose-200"
    return "bg-gray-500/15 text-gray-200"
  }

  const getStatusBadgeColor = (status: string) => {
    const statusLower = status.toLowerCase()
    if (statusLower === "executed" || statusLower === "completed") return "bg-emerald-500/15 text-emerald-200"
    if (statusLower === "pending") return "bg-amber-500/15 text-amber-200"
    if (statusLower === "failed" || statusLower === "rejected") return "bg-rose-500/15 text-rose-200"
    if (statusLower === "cancelled") return "bg-gray-500/15 text-gray-200"
    return "bg-blue-500/15 text-blue-200"
  }

  return (
    <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader>
        <CardTitle className="h-title text-xl text-[#fafafa]">Recent Trades</CardTitle>
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Latest executions
        </CardDescription>
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden">
        {trades.filter(t => t.status === "executed").length === 0 ? (
          <div className="flex h-full min-h-[300px] w-full items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/20 text-sm text-white/50">
            No executed trades yet
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-white/10">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-white/45">
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Symbol</th>
                  <th className="px-4 py-3">Side</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Executed Price</th>
                  <th className="px-4 py-3">Current Price</th>
                  <th className="px-4 py-3">Quantity</th>
                  <th className="px-4 py-3">Net Amount</th>
                  <th className="px-4 py-3">Response Time</th>
                  <th className="px-4 py-3">Source</th>
                  <th className="px-4 py-3 text-right">Trade Type</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {trades.filter(trade => trade.status === "executed").map((trade, index) => {
                  const netAmount = parseFloat(trade.net_amount || "0")
                  const isPositive = netAmount >= 0
                  
                  // Format triggered_by for display
                  const formatTriggeredBy = (triggeredBy?: string) => {
                    if (!triggeredBy || triggeredBy === "manual") return "Manual"
                    if (triggeredBy.startsWith("alpha_signal:")) {
                      return triggeredBy.replace("alpha_signal:", "Alpha: ")
                    }
                    if (triggeredBy === "nse_filings_pipeline") return "NSE Filings"
                    if (triggeredBy === "manual_api_trade") return "API"
                    return triggeredBy
                  }

                  return (
                    <motion.tr
                      key={trade.id || index}
                      variants={rowVariants}
                      initial="hidden"
                      animate="show"
                      className="text-sm text-white/80"
                    >
                      <td className="px-4 py-3 whitespace-nowrap">
                        {formatTime(trade.execution_time || trade.created_at)}
                      </td>
                      <td className="px-4 py-3 font-semibold text-[#fafafa]">{trade.symbol}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold uppercase ${getSideBadgeColor(trade.side)}`}
                        >
                          {trade.side}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold uppercase ${getStatusBadgeColor(trade.status)}`}
                        >
                          {trade.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-emerald-300">
                        {formatCurrency(trade.executed_price)}
                      </td>
                      <td className="px-4 py-3">
                        {pricesLoading && currentPrices.size === 0 ? (
                          <span className="text-white/40 text-xs">Loading...</span>
                        ) : currentPrices.has(trade.symbol) ? (
                          <span className="text-blue-300">{formatCurrency(currentPrices.get(trade.symbol))}</span>
                        ) : (
                          <span className="text-white/40">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-white/80">
                        {trade.executed_quantity || trade.quantity || "—"}
                      </td>
                      <td className={`px-4 py-3 font-semibold ${isPositive ? "text-emerald-300" : "text-rose-300"}`}>
                        {formatCurrency(trade.net_amount)}
                      </td>
                      <td className="px-4 py-3 text-blue-300">
                        {formatDuration(trade.llm_delay)}
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs text-white/60">
                          {formatTriggeredBy(trade.triggered_by)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className="inline-flex items-center rounded-full bg-sky-500/15 px-3 py-1 text-xs font-semibold text-sky-200">
                          {trade.trade_type || "—"}
                        </span>
                      </td>
                    </motion.tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// =====================================================
// ADVANCED TABLE - Used for alphas page with pagination
// =====================================================
function AdvancedTradesTable({ initialTrades, initialLoading, agentId }: { initialTrades?: AgentTrade[]; initialLoading?: boolean; agentId?: string }) {
  const [trades, setTrades] = useState<AgentTrade[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<typeof PAGE_SIZE_OPTIONS[number]>(10)
  const [total, setTotal] = useState(0)
  const [currentPrices, setCurrentPrices] = useState<Map<string, number>>(new Map())
  const [pricesLoading, setPricesLoading] = useState(false)
  
  // Track if we've done initial fetch
  const hasInitialized = useRef(false)

  // Fetch trades with pagination
  const fetchTrades = useCallback(async (targetPage: number, targetPageSize: number) => {
    setLoading(true)
    try {
      const response = await getRecentTrades(targetPage, targetPageSize, undefined, undefined, undefined, undefined, agentId)
      setTrades(response.items as unknown as AgentTrade[])
      setTotal(response.total)
    } catch (error) {
      console.error("Failed to fetch trades:", error)
    } finally {
      setLoading(false)
    }
  }, [agentId])

  // Fetch current prices for symbols in trades
  const fetchCurrentPrices = useCallback(async (tradesList: AgentTrade[]) => {
    if (tradesList.length === 0) return

    const symbols = [...new Set(tradesList.map((t) => t.symbol).filter(Boolean))]
    if (symbols.length === 0) return

    setPricesLoading(true)
    try {
      const response = await fetchQuotes(symbols)
      if (response?.data) {
        const priceMap = new Map<string, number>()
        response.data.forEach((quote) => {
          if (quote?.symbol && quote?.price) {
            priceMap.set(quote.symbol, parseFloat(quote.price))
          }
        })
        setCurrentPrices(priceMap)
      }
    } catch (error) {
      console.error("Failed to fetch current prices:", error)
    } finally {
      setPricesLoading(false)
    }
  }, [])

  // Fetch on mount to get actual total count (wait for agentId to be available)
  useEffect(() => {
    if (!hasInitialized.current && agentId) {
      hasInitialized.current = true
      fetchTrades(1, pageSize)
    }
  }, [fetchTrades, pageSize, agentId])

  // Fetch prices whenever trades change
  useEffect(() => {
    if (trades.length > 0) {
      fetchCurrentPrices(trades)
    }
  }, [trades, fetchCurrentPrices])

  // Process trades into pairs (completed round trips) and open positions
  const { tradePairs, openPositions, totalRealizedPnl } = useMemo(() => {
    const pairs: TradePair[] = []
    const openPos: OpenPosition[] = []
    
    // Group trades by symbol
    const tradesBySymbol = new Map<string, AgentTrade[]>()
    trades.forEach((trade) => {
      const existing = tradesBySymbol.get(trade.symbol) || []
      existing.push(trade)
      tradesBySymbol.set(trade.symbol, existing)
    })

    // For each symbol, match buy/sell pairs
    tradesBySymbol.forEach((symbolTrades, symbol) => {
      const buys = symbolTrades.filter((t) => t.side.toLowerCase() === "buy").sort((a, b) => 
        new Date(a.execution_time || a.created_at).getTime() - new Date(b.execution_time || b.created_at).getTime()
      )
      const sells = symbolTrades.filter((t) => t.side.toLowerCase() === "sell").sort((a, b) => 
        new Date(a.execution_time || a.created_at).getTime() - new Date(b.execution_time || b.created_at).getTime()
      )

      // Match pairs (FIFO)
      const minPairs = Math.min(buys.length, sells.length)
      for (let i = 0; i < minPairs; i++) {
        const buyTrade = buys[i]
        const sellTrade = sells[i]
        const buyPrice = parseFloat(buyTrade.executed_price || "0")
        const sellPrice = parseFloat(sellTrade.executed_price || "0")
        const buyAmount = parseFloat(buyTrade.net_amount || "0")
        const sellAmount = parseFloat(sellTrade.net_amount || "0")
        const quantity = Math.round(buyAmount / buyPrice) || 1

        const pnl = sellAmount - buyAmount
        const pnlPercent = buyAmount > 0 ? (pnl / buyAmount) * 100 : 0

        // Calculate holding time
        const buyTime = new Date(buyTrade.execution_time || buyTrade.created_at)
        const sellTime = new Date(sellTrade.execution_time || sellTrade.created_at)
        const holdingMs = sellTime.getTime() - buyTime.getTime()
        const holdingMins = Math.round(holdingMs / 60000)
        const holdingTime = holdingMins < 60 
          ? `${holdingMins}m` 
          : holdingMins < 1440 
            ? `${Math.round(holdingMins / 60)}h` 
            : `${Math.round(holdingMins / 1440)}d`

        pairs.push({
          symbol,
          buyTrade,
          sellTrade,
          buyPrice,
          sellPrice,
          quantity,
          pnl,
          pnlPercent,
          holdingTime,
        })
      }

      // Add remaining unmatched trades as open positions
      for (let i = minPairs; i < buys.length; i++) {
        const trade = buys[i]
        const price = parseFloat(trade.executed_price || "0")
        const amount = parseFloat(trade.net_amount || "0")
        openPos.push({
          symbol,
          trade,
          side: "BUY",
          price,
          quantity: Math.round(amount / price) || 1,
        })
      }
      for (let i = minPairs; i < sells.length; i++) {
        const trade = sells[i]
        const price = parseFloat(trade.executed_price || "0")
        const amount = parseFloat(trade.net_amount || "0")
        openPos.push({
          symbol,
          trade,
          side: "SELL",
          price,
          quantity: Math.round(amount / price) || 1,
        })
      }
    })

    // Sort pairs by sell time (most recent first)
    pairs.sort((a, b) => 
      new Date(b.sellTrade.execution_time || b.sellTrade.created_at).getTime() - 
      new Date(a.sellTrade.execution_time || a.sellTrade.created_at).getTime()
    )

    // Calculate total realized P&L
    const totalPnl = pairs.reduce((sum, p) => sum + p.pnl, 0)

    // Add current prices to open positions
    openPos.forEach((pos) => {
      const currentPrice = currentPrices.get(pos.symbol)
      if (currentPrice) {
        pos.currentPrice = currentPrice
        if (pos.side === "BUY") {
          pos.unrealizedPnl = (currentPrice - pos.price) * pos.quantity
          pos.unrealizedPnlPercent = ((currentPrice - pos.price) / pos.price) * 100
        } else {
          pos.unrealizedPnl = (pos.price - currentPrice) * pos.quantity
          pos.unrealizedPnlPercent = ((pos.price - currentPrice) / pos.price) * 100
        }
      }
    })

    return { tradePairs: pairs, openPositions: openPos, totalRealizedPnl: totalPnl }
  }, [trades, currentPrices])

  // Handle page size change
  const handlePageSizeChange = (newSize: typeof PAGE_SIZE_OPTIONS[number]) => {
    setPageSize(newSize)
    setPage(1)
    fetchTrades(1, newSize)
  }

  // Handle page change
  const handlePageChange = (newPage: number) => {
    setPage(newPage)
    fetchTrades(newPage, pageSize)
  }

  // Refresh handler
  const handleRefresh = () => {
    fetchTrades(page, pageSize)
  }

  const totalPages = Math.ceil(total / pageSize)
  const isLoading = loading || initialLoading

  if (isLoading && trades.length === 0) {
    return (
      <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur">
        <CardHeader>
          <CardTitle className="h-title text-xl text-[#fafafa]">Recent Trades</CardTitle>
          <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
            Loading trades...
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="animate-pulse rounded-xl border border-white/10 bg-white/8 p-4">
                <div className="h-4 w-full rounded bg-white/20" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  const formatTime = (dateString: string) => {
    try {
      return new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }).format(new Date(dateString))
    } catch {
      return dateString
    }
  }

  return (
    <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="h-title text-xl text-[#fafafa]">Trade History</CardTitle>
            <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
              {tradePairs.length > 0 ? (
                <span className="flex items-center gap-2">
                  <span>{tradePairs.length} completed trades</span>
                  <span className="text-white/30">•</span>
                  <span className={totalRealizedPnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
                    {totalRealizedPnl >= 0 ? "+" : ""}{formatCurrencyInteger(totalRealizedPnl)} P&L
                  </span>
                </span>
              ) : "Latest executions"}
            </CardDescription>
          </div>
          <div className="flex items-center gap-3">
            {/* Page Size Selector */}
            <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-black/20 p-1">
              {PAGE_SIZE_OPTIONS.map((size) => (
                <button
                  key={size}
                  onClick={() => handlePageSizeChange(size)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                    pageSize === size
                      ? "bg-white/15 text-white"
                      : "text-white/50 hover:text-white/80"
                  }`}
                >
                  {size}
                </button>
              ))}
            </div>
            {/* Page Navigation Arrows */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => handlePageChange(Math.max(1, page - 1))}
                disabled={page === 1 || isLoading}
                className="rounded-md border border-white/10 bg-black/20 p-1.5 text-white/50 transition hover:bg-white/10 hover:text-white/80 disabled:cursor-not-allowed disabled:opacity-30"
                title="Previous page"
              >
                <ChevronLeft className="size-4" />
              </button>
              {totalPages > 0 && (
                <span className="px-2 text-xs text-white/50">
                  {page}/{totalPages}
                </span>
              )}
              <button
                onClick={() => handlePageChange(Math.min(totalPages || 1, page + 1))}
                disabled={page >= totalPages || isLoading}
                className="rounded-md border border-white/10 bg-black/20 p-1.5 text-white/50 transition hover:bg-white/10 hover:text-white/80 disabled:cursor-not-allowed disabled:opacity-30"
                title="Next page"
              >
                <ChevronRight className="size-4" />
              </button>
            </div>
            {/* Refresh Button */}
            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={isLoading || pricesLoading}
              className="border-white/10 bg-black/20 text-white/60 hover:bg-white/10 hover:text-white"
            >
              <RefreshCw className={`size-4 ${(isLoading || pricesLoading) ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden">
        {trades.length === 0 ? (
          <div className="flex h-full min-h-[300px] w-full items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/20 text-sm text-white/50">
            No trades yet
          </div>
        ) : (
          <>
            {/* Completed Trade Pairs Table */}
            {tradePairs.length > 0 && (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-white/10">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wider text-white/45">
                      <th className="px-3 py-3">Symbol</th>
                      <th className="px-3 py-3">Entry</th>
                      <th className="px-3 py-3">Exit</th>
                      <th className="px-3 py-3">Qty</th>
                      <th className="px-3 py-3">Buy Price</th>
                      <th className="px-3 py-3">Sell Price</th>
                      <th className="px-3 py-3">P&L</th>
                      <th className="px-3 py-3">Return</th>
                      <th className="px-3 py-3 text-right">Held</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/10">
                    {tradePairs.map((pair, index) => (
                      <motion.tr
                        key={`${pair.symbol}-${index}`}
                        variants={rowVariants}
                        initial="hidden"
                        animate="show"
                        className="text-sm text-white/80"
                      >
                        <td className="px-3 py-3">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-[#fafafa]">{pair.symbol}</span>
                            <ArrowRightLeft className="size-3 text-white/30" />
                          </div>
                        </td>
                        <td className="px-3 py-3 whitespace-nowrap text-white/60">
                          {formatTime(pair.buyTrade.execution_time || pair.buyTrade.created_at)}
                        </td>
                        <td className="px-3 py-3 whitespace-nowrap text-white/60">
                          {formatTime(pair.sellTrade.execution_time || pair.sellTrade.created_at)}
                        </td>
                        <td className="px-3 py-3 text-white/70">
                          {pair.quantity}
                        </td>
                        <td className="px-3 py-3">
                          <span className="text-emerald-300">{formatCurrencyInteger(pair.buyPrice)}</span>
                        </td>
                        <td className="px-3 py-3">
                          <span className="text-rose-300">{formatCurrencyInteger(pair.sellPrice)}</span>
                        </td>
                        <td className="px-3 py-3">
                          <div className={`flex items-center gap-1 font-semibold ${pair.pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                            {pair.pnl >= 0 ? <TrendingUp className="size-3.5" /> : <TrendingDown className="size-3.5" />}
                            {pair.pnl >= 0 ? "+" : ""}{formatCurrencyInteger(pair.pnl)}
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${
                            pair.pnlPercent >= 0 
                              ? "bg-emerald-500/15 text-emerald-300" 
                              : "bg-rose-500/15 text-rose-300"
                          }`}>
                            {pair.pnlPercent >= 0 ? "+" : ""}{pair.pnlPercent.toFixed(2)}%
                          </span>
                        </td>
                        <td className="px-3 py-3 text-right">
                          <span className="inline-flex items-center rounded-full bg-sky-500/15 px-2 py-0.5 text-xs font-semibold text-sky-200">
                            {pair.holdingTime}
                          </span>
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Open Positions Section */}
            {openPositions.length > 0 && (
              <div className="mt-6">
                <h4 className="mb-3 text-xs font-medium uppercase tracking-wider text-white/45">
                  Open Positions ({openPositions.length})
                </h4>
                <div className="overflow-x-auto rounded-lg border border-white/10 bg-black/20">
                  <table className="min-w-full divide-y divide-white/10">
                    <thead>
                      <tr className="text-left text-xs uppercase tracking-wider text-white/45">
                        <th className="px-3 py-2">Symbol</th>
                        <th className="px-3 py-2">Side</th>
                        <th className="px-3 py-2">Entry Price</th>
                        <th className="px-3 py-2">Current</th>
                        <th className="px-3 py-2 text-right">Unrealized P&L</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/10">
                      {openPositions.map((pos, index) => (
                        <tr key={`open-${pos.symbol}-${index}`} className="text-sm text-white/70">
                          <td className="px-3 py-2 font-semibold text-[#fafafa]">{pos.symbol}</td>
                          <td className="px-3 py-2">
                            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${
                              pos.side === "BUY" ? "bg-emerald-500/15 text-emerald-200" : "bg-rose-500/15 text-rose-200"
                            }`}>
                              {pos.side}
                            </span>
                          </td>
                          <td className="px-3 py-2">{formatCurrencyInteger(pos.price)}</td>
                          <td className="px-3 py-2">
                            {pos.currentPrice ? formatCurrencyInteger(pos.currentPrice) : "—"}
                          </td>
                          <td className="px-3 py-2 text-right">
                            {pos.unrealizedPnl !== undefined ? (
                              <span className={pos.unrealizedPnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
                                {pos.unrealizedPnl >= 0 ? "+" : ""}{formatCurrencyInteger(pos.unrealizedPnl)}
                                <span className="ml-1 text-xs">
                                  ({pos.unrealizedPnlPercent?.toFixed(1)}%)
                                </span>
                              </span>
                            ) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Show message if no pairs could be matched */}
            {tradePairs.length === 0 && openPositions.length === 0 && (
              <div className="flex h-full min-h-[200px] w-full items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/20 text-sm text-white/50">
                No completed round trips found
              </div>
            )}

            {/* Pagination Info */}
            {total > 0 && (
              <div className="mt-4 border-t border-white/10 pt-4">
                <div className="text-xs text-white/50">
                  Showing {((page - 1) * pageSize) + 1} - {Math.min(page * pageSize, total)} of {total} trades
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

// =====================================================
// MAIN EXPORT - Switches between simple and advanced modes
// =====================================================
export function AgentTradesTable({ trades = [], loading = false, agentType, agentId, mode = "simple" }: AgentTradesTableProps) {
  if (mode === "advanced") {
    return <AdvancedTradesTable initialTrades={trades} initialLoading={loading} agentId={agentId} />
  }
  
  return <SimpleTradesTable trades={trades} loading={loading} />
}
