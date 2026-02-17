"use client"

import type { ComponentPropsWithoutRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { PositionMetrics } from "@/lib/admin"
import { formatCurrency } from "@/lib/admin"

type PositionMetricsCardProps = {
  data: PositionMetrics | null
  title?: string
  className?: string
  loading?: boolean
} & ComponentPropsWithoutRef<typeof Card>

export function PositionMetricsCard({ data, title = "Position Metrics", className = "", loading = false, ...cardProps }: PositionMetricsCardProps) {
  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {Array.from({ length: 6 }).map((_, i) => (
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

  const openPercentage = data.total_positions > 0 ? ((data.open_positions / data.total_positions) * 100).toFixed(1) : "0"
  const longPercentage = (data.long_positions + data.short_positions) > 0
    ? ((data.long_positions / (data.long_positions + data.short_positions)) * 100).toFixed(1)
    : "0"

  return (
    <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <MetricItem label="Total Positions" value={data.total_positions.toLocaleString("en-IN")} />
          <MetricItem
            label="Open Positions"
            value={`${data.open_positions.toLocaleString("en-IN")} (${openPercentage}%)`}
            highlight
          />
          <MetricItem label="Closed Positions" value={data.closed_positions.toLocaleString("en-IN")} />
          <MetricItem
            label="Long Positions"
            value={`${data.long_positions.toLocaleString("en-IN")} (${longPercentage}%)`}
          />
          <MetricItem label="Short Positions" value={data.short_positions.toLocaleString("en-IN")} />
          <MetricItem label="Total Invested" value={formatCurrency(data.total_invested_in_positions)} highlight />
        </div>
      </CardContent>
    </Card>
  )
}

function MetricItem({ label, value, highlight = false, className = "" }: { label: string; value: string; highlight?: boolean; className?: string }) {
  return (
    <div className={`rounded-xl border border-white/10 bg-white/5 p-4 ${highlight ? "ring-2 ring-emerald-500/30" : ""} ${className}`}>
      <div className="text-xs text-white/60">{label}</div>
      <div className="mt-1 text-lg font-semibold text-[#fafafa]">{value}</div>
    </div>
  )
}

