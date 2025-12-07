"use client"

import { useState, useEffect, useCallback } from "react"
import { motion } from "framer-motion"
import { ChevronLeft, ChevronRight, RefreshCw, TrendingUp, TrendingDown, Search, X } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"
import { getRecentTrades, fetchQuotes } from "@/lib/portfolio"
import { formatCurrency, formatDate } from "@/lib/utils/formatters"
import type { Trade } from "@/lib/portfolio"

const rowVariants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.2 } },
}

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const

interface IntradayTradesTableProps {
  className?: string
  agentId?: string
}

export function IntradayTradesTable({ className, agentId }: IntradayTradesTableProps) {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<typeof PAGE_SIZE_OPTIONS[number]>(10)
  const [total, setTotal] = useState(0)
  const [livePrices, setLivePrices] = useState<Map<string, number>>(new Map())
  
  // Filters
  const [symbolFilter, setSymbolFilter] = useState("")
  const [sideFilter, setSideFilter] = useState<string>("all")
  const [orderTypeFilter, setOrderTypeFilter] = useState<string>("all")
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [showPending, setShowPending] = useState(false)
  
  // Applied filters (for actual API calls)
  const [appliedFilters, setAppliedFilters] = useState({
    symbol: "",
    side: "all",
    orderType: "all",
    status: "all",
    showPending: false,
  })

  // Fetch trades with filters
  const fetchTrades = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await getRecentTrades(
        page,
        pageSize,
        appliedFilters.symbol || undefined,
        appliedFilters.side !== "all" ? appliedFilters.side : undefined,
        appliedFilters.orderType !== "all" ? appliedFilters.orderType : undefined,
        appliedFilters.status !== "all" ? appliedFilters.status : undefined,
        agentId
      )
      
      // Filter out pending trades on client side if showPending is false
      // Include pending, pending_tp, pending_sl statuses
      let filteredTrades = response.items
      if (!appliedFilters.showPending && appliedFilters.status === "all") {
        filteredTrades = response.items.filter(trade => {
          const status = trade.status.toLowerCase()
          return !status.includes("pending")
        })
      }
      
      setTrades(filteredTrades)
      setTotal(filteredTrades.length)
      
      // Fetch live prices for all unique symbols
      const symbols = [...new Set(filteredTrades.map(t => t.symbol))]
      if (symbols.length > 0) {
        try {
          const quotesResponse = await fetchQuotes(symbols)
          const priceMap = new Map<string, number>()
          quotesResponse.data.forEach((quote) => {
            if (quote && quote.symbol && quote.price) {
              priceMap.set(quote.symbol, parseFloat(quote.price))
            }
          })
          setLivePrices(priceMap)
        } catch (quoteErr) {
          console.warn("Failed to fetch live prices:", quoteErr)
          // Continue without live prices
        }
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Failed to load trades"
      console.error("Failed to fetch trades:", err)
      console.error("Error details:", {
        message: errorMessage,
        error: err,
      })
      setError(errorMessage)
      setTrades([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, appliedFilters, agentId])

  useEffect(() => {
    fetchTrades()
  }, [fetchTrades])

  // Auto-refresh every 5 seconds
  useEffect(() => {
    const interval = setInterval(fetchTrades, 5000)
    return () => clearInterval(interval)
  }, [fetchTrades])

  const handleApplyFilters = () => {
    setAppliedFilters({
      symbol: symbolFilter,
      side: sideFilter,
      orderType: orderTypeFilter,
      status: statusFilter,
      showPending: showPending,
    })
    setPage(1) // Reset to first page when applying filters
  }

  const handleClearFilters = () => {
    setSymbolFilter("")
    setSideFilter("all")
    setOrderTypeFilter("all")
    setStatusFilter("all")
    setShowPending(false)
    setAppliedFilters({
      symbol: "",
      side: "all",
      orderType: "all",
      status: "all",
      showPending: false,
    })
    setPage(1)
  }

  const totalPages = Math.ceil(total / pageSize)
  const hasFilters = symbolFilter || sideFilter !== "all" || orderTypeFilter !== "all" || statusFilter !== "all" || showPending

  return (
    <Card className={`card-glass flex flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur ${className}`}>
      <CardHeader className="border-b border-white/10 pb-5">
        <div className="flex items-center justify-between">
          <CardTitle className="h-title text-xl text-[#fafafa]">
            Intraday Trades
          </CardTitle>
          <Button
            onClick={fetchTrades}
            size="sm"
            variant="ghost"
            className="text-white/60 hover:text-white"
          >
            <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
        
        {/* Filters */}
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-white/40" />
            <Input
              placeholder="Search symbol..."
              value={symbolFilter}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSymbolFilter(e.target.value)}
              onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && handleApplyFilters()}
              className="border-white/10 bg-white/5 pl-9 text-white placeholder:text-white/40 focus:border-white/20"
            />
          </div>
          
          <Select value={sideFilter} onValueChange={setSideFilter}>
            <SelectTrigger className="border-white/10 bg-white/5 text-white">
              <SelectValue placeholder="Side" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Sides</SelectItem>
              <SelectItem value="buy">Buy</SelectItem>
              <SelectItem value="sell">Sell</SelectItem>
              <SelectItem value="short_sell">Short Sell</SelectItem>
            </SelectContent>
          </Select>
          
          <Select value={orderTypeFilter} onValueChange={setOrderTypeFilter}>
            <SelectTrigger className="border-white/10 bg-white/5 text-white">
              <SelectValue placeholder="Order Type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              <SelectItem value="market">Market</SelectItem>
              <SelectItem value="limit">Limit</SelectItem>
            </SelectContent>
          </Select>
          
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="border-white/10 bg-white/5 text-white">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Status</SelectItem>
              <SelectItem value="executed">Executed</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="cancelled">Cancelled</SelectItem>
              <SelectItem value="rejected">Rejected</SelectItem>
            </SelectContent>
          </Select>
        </div>
        
        {/* Filter Actions */}
        <div className="mt-3 flex items-center gap-2">
          <Button
            onClick={handleApplyFilters}
            size="sm"
            className="border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
          >
            Apply Filters
          </Button>
          {hasFilters && (
            <Button
              onClick={handleClearFilters}
              size="sm"
              variant="ghost"
              className="text-white/60 hover:text-white"
            >
              <X className="mr-1 size-4" />
              Clear
            </Button>
          )}
          <div className="ml-4 flex items-center gap-2">
            <Checkbox
              id="show-pending"
              checked={showPending}
              onCheckedChange={(checked) => {
                const newValue = checked as boolean
                setShowPending(newValue)
                // Immediately apply the filter
                setAppliedFilters(prev => ({
                  ...prev,
                  showPending: newValue,
                }))
              }}
              className="border-white/20 data-[state=checked]:bg-emerald-500 data-[state=checked]:border-emerald-500"
            />
            <label
              htmlFor="show-pending"
              className="text-sm text-white/70 cursor-pointer select-none"
            >
              Show Pending
            </label>
          </div>
          <span className="ml-auto text-xs text-white/40">
            {total} total trade{total !== 1 ? "s" : ""}
          </span>
        </div>
      </CardHeader>

      <CardContent className="flex-1 overflow-auto p-0">
        {loading && trades.length === 0 ? (
          <div className="flex h-64 items-center justify-center">
            <RefreshCw className="size-6 animate-spin text-white/40" />
          </div>
        ) : error ? (
          <div className="flex h-64 flex-col items-center justify-center gap-2">
            <div className="text-rose-400">{error}</div>
            <Button
              onClick={fetchTrades}
              size="sm"
              variant="ghost"
              className="text-white/60 hover:text-white"
            >
              <RefreshCw className="mr-2 size-4" />
              Retry
            </Button>
          </div>
        ) : trades.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-white/40">
            No trades found
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="sticky top-0 z-10 border-b border-white/10 bg-white/5 backdrop-blur">
                <tr className="text-left text-xs uppercase tracking-wider text-white/60">
                  <th className="px-6 py-4 font-medium">Symbol</th>
                  <th className="px-6 py-4 font-medium">Side</th>
                  <th className="px-6 py-4 font-medium">Type</th>
                  <th className="px-6 py-4 font-medium">Quantity</th>
                  <th className="px-6 py-4 font-medium">Executed Price</th>
                  <th className="px-6 py-4 font-medium">Current Price</th>
                  <th className="px-6 py-4 font-medium">Net Amount</th>
                  <th className="px-6 py-4 font-medium">Status</th>
                  <th className="px-6 py-4 font-medium">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {trades.map((trade, index) => (
                  <motion.tr
                    key={trade.id}
                    variants={rowVariants}
                    initial="hidden"
                    animate="show"
                    transition={{ delay: index * 0.02 }}
                    className="group hover:bg-white/5"
                  >
                    <td className="px-6 py-4">
                      <span className="font-mono text-sm font-semibold text-white">
                        {trade.symbol}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex items-center gap-1 text-sm font-medium ${
                          trade.side.toLowerCase() === "buy"
                            ? "text-emerald-400"
                            : "text-rose-400"
                        }`}
                      >
                        {trade.side.toLowerCase() === "buy" ? (
                          <TrendingUp className="size-3" />
                        ) : (
                          <TrendingDown className="size-3" />
                        )}
                        {trade.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm text-white/70 capitalize">
                      {trade.order_type}
                    </td>
                    <td className="px-6 py-4 text-sm text-white/70">
                      {trade.executed_quantity > 0
                        ? `${trade.executed_quantity} / ${trade.quantity}`
                        : trade.quantity}
                    </td>
                    <td className="px-6 py-4 text-sm text-white/70">
                      {trade.executed_price
                        ? formatCurrency(parseFloat(trade.executed_price))
                        : "-"}
                    </td>
                    <td className="px-6 py-4">
                      {(() => {
                        const currentPrice = livePrices.get(trade.symbol)
                        const executedPrice = trade.executed_price ? parseFloat(trade.executed_price) : null
                        
                        if (!currentPrice || !executedPrice) {
                          return <span className="text-sm text-white/40">-</span>
                        }
                        
                        const priceDiff = currentPrice - executedPrice
                        const priceDiffPct = (priceDiff / executedPrice) * 100
                        const isProfit = trade.side.toLowerCase() === "buy" ? priceDiff > 0 : priceDiff < 0
                        
                        return (
                          <div className="flex flex-col gap-0.5">
                            <span className="text-sm font-medium text-white">
                              {formatCurrency(currentPrice)}
                            </span>
                            {Math.abs(priceDiff) > 0.01 && (
                              <span className={`text-xs ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                                {isProfit ? "+" : ""}{priceDiffPct.toFixed(2)}%
                              </span>
                            )}
                          </div>
                        )
                      })()}
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm font-medium text-white">
                        {formatCurrency(parseFloat(trade.net_amount))}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${
                          trade.status.toLowerCase() === "executed"
                            ? "bg-emerald-500/20 text-emerald-300"
                            : trade.status.toLowerCase() === "pending"
                            ? "bg-amber-500/20 text-amber-300"
                            : trade.status.toLowerCase() === "cancelled"
                            ? "bg-gray-500/20 text-gray-300"
                            : "bg-rose-500/20 text-rose-300"
                        }`}
                      >
                        {trade.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-xs text-white/50">
                      {formatDate(trade.execution_time || trade.created_at)}
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>

      {/* Pagination */}
      {total > 0 && (
        <div className="flex items-center justify-between border-t border-white/10 px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="text-sm text-white/60">Rows per page:</span>
            <Select
              value={String(pageSize)}
              onValueChange={(val: string) => {
                setPageSize(Number(val) as typeof PAGE_SIZE_OPTIONS[number])
                setPage(1)
              }}
            >
              <SelectTrigger className="h-8 w-20 border-white/10 bg-white/5 text-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PAGE_SIZE_OPTIONS.map((size) => (
                  <SelectItem key={size} value={String(size)}>
                    {size}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-sm text-white/60">
              Page {page} of {totalPages}
            </span>
            <div className="flex gap-1">
              <Button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                size="sm"
                variant="ghost"
                className="text-white/60 hover:text-white disabled:opacity-30"
              >
                <ChevronLeft className="size-4" />
              </Button>
              <Button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                size="sm"
                variant="ghost"
                className="text-white/60 hover:text-white disabled:opacity-30"
              >
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  )
}
