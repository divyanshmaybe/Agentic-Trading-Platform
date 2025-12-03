"use client"

import { motion } from "framer-motion"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { AgentTrade } from "@/lib/types/agent"
import { formatCurrency, formatNumber, formatDuration } from "@/lib/utils/formatters"

const rowVariants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.2 } },
}
	
interface AgentTradesTableProps {
  trades: AgentTrade[]
  loading: boolean
}

export function AgentTradesTable({ trades, loading }: AgentTradesTableProps) {
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
        {trades.length === 0 ? (
          <div className="flex h-full min-h-[300px] w-full items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/20 text-sm text-white/50">
            No trades yet
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
                  <th className="px-4 py-3">Net Amount</th>
                  <th className="px-4 py-3">Response Time</th>
                  <th className="px-4 py-3 text-right">Trade Type</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {trades.map((trade, index) => {
                  const netAmount = parseFloat(trade.net_amount || "0")
                  const isPositive = netAmount >= 0

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
                      <td className={`px-4 py-3 font-semibold ${isPositive ? "text-emerald-300" : "text-rose-300"}`}>
                        {formatCurrency(trade.net_amount)}
                      </td>
                      <td className="px-4 py-3 text-blue-300">
                        {formatDuration(trade.llm_delay)}
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
