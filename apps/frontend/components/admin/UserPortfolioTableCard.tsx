"use client"

import { useState, useMemo } from "react"
import type { ComponentPropsWithoutRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react"
import type { UserPortfolio } from "@/lib/admin"
import { formatCurrency } from "@/lib/admin"

type UserPortfolioTableCardProps = {
  data: UserPortfolio[]
  title?: string
  className?: string
  loading?: boolean
} & ComponentPropsWithoutRef<typeof Card>

type SortField = "portfolio_name" | "investment_amount" | "current_value" | "realized_pnl" | "roi_percentage" | "total_trades" | "open_positions"
type SortDirection = "asc" | "desc"

export function UserPortfolioTableCard({ data, title = "User Portfolio Metrics", className = "", loading = false, ...cardProps }: UserPortfolioTableCardProps) {
  const [sortField, setSortField] = useState<SortField>("realized_pnl")
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc")

  const sortedData = useMemo(() => {
    return [...data].sort((a, b) => {
      let comparison = 0
      switch (sortField) {
        case "portfolio_name":
          comparison = a.portfolio_name.localeCompare(b.portfolio_name)
          break
        case "investment_amount":
          comparison = a.investment_amount - b.investment_amount
          break
        case "current_value":
          comparison = a.current_value - b.current_value
          break
        case "realized_pnl":
          comparison = a.realized_pnl - b.realized_pnl
          break
        case "roi_percentage":
          comparison = a.roi_percentage - b.roi_percentage
          break
        case "total_trades":
          comparison = a.total_trades - b.total_trades
          break
        case "open_positions":
          comparison = a.open_positions - b.open_positions
          break
      }
      return sortDirection === "asc" ? comparison : -comparison
    })
  }, [data, sortField, sortDirection])

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc")
    } else {
      setSortField(field)
      setSortDirection("desc")
    }
  }

  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-96 animate-pulse rounded-xl bg-white/5" />
        </CardContent>
      </Card>
    )
  }

  if (!data || data.length === 0) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-48 items-center justify-center text-white/60">No data available</div>
        </CardContent>
      </Card>
    )
  }

  const SortButton = ({ field, label }: { field: SortField; label: string }) => {
    const isActive = sortField === field
    return (
      <button onClick={() => handleSort(field)} className="flex items-center gap-1 hover:text-white" type="button">
        {label}
        {isActive ? (
          sortDirection === "asc" ? (
            <ArrowUp className="size-3" />
          ) : (
            <ArrowDown className="size-3" />
          )
        ) : (
          <ArrowUpDown className="size-3 opacity-50" />
        )}
      </button>
    )
  }

  return (
    <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-xl border border-white/10 bg-white/5">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/10">
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">
                  <SortButton field="portfolio_name" label="Portfolio Name" />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">
                  <SortButton field="investment_amount" label="Investment" />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">
                  <SortButton field="current_value" label="Current Value" />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">
                  <SortButton field="realized_pnl" label="P&L" />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">
                  <SortButton field="roi_percentage" label="ROI" />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">
                  <SortButton field="total_trades" label="Trades" />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">
                  <SortButton field="open_positions" label="Open Positions" />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">Status</th>
              </tr>
            </thead>
            <tbody>
              {sortedData.map((portfolio) => (
                <tr key={portfolio.portfolio_id} className="border-b border-white/5 hover:bg-white/5">
                  <td className="px-4 py-3 text-sm text-white">{portfolio.portfolio_name}</td>
                  <td className="px-4 py-3 text-sm text-white/80">{formatCurrency(portfolio.investment_amount)}</td>
                  <td className="px-4 py-3 text-sm text-white/80">{formatCurrency(portfolio.current_value)}</td>
                  <td
                    className={`px-4 py-3 text-sm font-medium ${
                      portfolio.realized_pnl >= 0 ? "text-[#22c55e]" : "text-[#ef4444]"
                    }`}
                  >
                    {formatCurrency(portfolio.realized_pnl)}
                  </td>
                  <td
                    className={`px-4 py-3 text-sm font-medium ${
                      portfolio.roi_percentage >= 0 ? "text-[#22c55e]" : "text-[#ef4444]"
                    }`}
                  >
                    {portfolio.roi_percentage.toFixed(2)}%
                  </td>
                  <td className="px-4 py-3 text-sm text-white/80">{portfolio.total_trades.toLocaleString("en-IN")}</td>
                  <td className="px-4 py-3 text-sm text-white/80">{portfolio.open_positions.toLocaleString("en-IN")}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                        portfolio.status === "profit"
                          ? "bg-emerald-500/20 text-emerald-300"
                          : portfolio.status === "loss"
                            ? "bg-red-500/20 text-red-300"
                            : "bg-slate-500/20 text-slate-200"
                      }`}
                    >
                      {portfolio.status.charAt(0).toUpperCase() + portfolio.status.slice(1)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-4 text-center text-xs text-white/60">Showing {sortedData.length} portfolios</div>
      </CardContent>
    </Card>
  )
}

