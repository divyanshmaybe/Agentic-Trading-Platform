"use client"

import type { ComponentPropsWithoutRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AlertTriangle } from "lucide-react"
import type { TradingMetrics } from "@/lib/admin"
import { formatCurrency } from "@/lib/admin"

type TradingMetricsCardProps = {
  data: TradingMetrics | null
  title?: string
  className?: string
  loading?: boolean
} & ComponentPropsWithoutRef<typeof Card>

export function TradingMetricsCard({ data, title = "Trading Metrics", className = "", loading = false, ...cardProps }: TradingMetricsCardProps) {
  const hasHighFailures = data ? data.failed_trades > 0 && (data.failed_trades / data.total_trades) * 100 > 5 : false

  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {Array.from({ length: 12 }).map((_, i) => (
              <div key={i} className="h-20 animate-pulse rounded-xl bg-white/5" />
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!data) {
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

  return (
    <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
        {hasHighFailures && (
          <div className="mt-2 flex items-center gap-2 rounded-lg bg-amber-500/20 px-3 py-2 text-sm text-amber-200">
            <AlertTriangle className="size-4" />
            <span>High failure rate detected: {((data.failed_trades / data.total_trades) * 100).toFixed(1)}%</span>
          </div>
        )}
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <MetricItem label="Total Trades" value={data.total_trades.toLocaleString("en-IN")} />
          <MetricItem
            label="Trades Today"
            value={data.trades_today.toLocaleString("en-IN")}
            highlight={data.trades_today > 0}
          />
          <MetricItem label="Trades This Week" value={data.trades_this_week.toLocaleString("en-IN")} />
          <MetricItem label="Trades This Month" value={data.trades_this_month.toLocaleString("en-IN")} />
          <MetricItem label="Total Volume" value={formatCurrency(data.total_volume)} highlight />
          <MetricItem
            label="Success Rate"
            value={`${data.success_rate_percentage.toFixed(2)}%`}
            highlight={data.success_rate_percentage >= 90}
            valueClassName={data.success_rate_percentage >= 90 ? "text-[#22c55e]" : data.success_rate_percentage < 80 ? "text-[#ef4444]" : ""}
          />
          <MetricItem label="Successful Trades" value={data.successful_trades.toLocaleString("en-IN")} />
          <MetricItem
            label="Failed Trades"
            value={data.failed_trades.toLocaleString("en-IN")}
            valueClassName={data.failed_trades > 0 ? "text-[#ef4444]" : ""}
          />
          <MetricItem label="Pending Trades" value={data.pending_trades.toLocaleString("en-IN")} />
          <MetricItem label="Avg Trade Size" value={formatCurrency(data.avg_trade_size)} />
          <MetricItem label="Total Fees" value={formatCurrency(data.total_fees)} />
          <MetricItem label="Total Taxes" value={formatCurrency(data.total_taxes)} />
        </div>
      </CardContent>
    </Card>
  )
}

function MetricItem({
  label,
  value,
  highlight = false,
  valueClassName = "",
  className = "",
}: {
  label: string
  value: string
  highlight?: boolean
  valueClassName?: string
  className?: string
}) {
  return (
    <div className={`rounded-xl border border-white/10 bg-white/5 p-4 ${highlight ? "ring-2 ring-emerald-500/30" : ""} ${className}`}>
      <div className="text-xs text-white/60">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${valueClassName || "text-[#fafafa]"}`}>{value}</div>
    </div>
  )
}

