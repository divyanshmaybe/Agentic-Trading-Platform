"use client"

import type { ComponentPropsWithoutRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { AlphaMetrics } from "@/lib/admin"

type AlphaMetricsCardProps = {
  data: AlphaMetrics | null
  title?: string
  className?: string
  loading?: boolean
} & ComponentPropsWithoutRef<typeof Card>

export function AlphaMetricsCard({ data, title = "Alpha Copilot Metrics", className = "", loading = false, ...cardProps }: AlphaMetricsCardProps) {
  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {Array.from({ length: 9 }).map((_, i) => (
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

  const completionRate = data.total_runs > 0
    ? ((data.completed_runs / data.total_runs) * 100).toFixed(1)
    : "0"
  const signalExecutionRate = data.total_alpha_signals > 0
    ? ((data.executed_signals / data.total_alpha_signals) * 100).toFixed(1)
    : "0"

  return (
    <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <MetricItem label="Total Runs" value={data.total_runs.toLocaleString("en-IN")} />
          <MetricItem
            label="Completion Rate"
            value={`${completionRate}%`}
            highlight={parseFloat(completionRate) >= 80}
            valueClassName={parseFloat(completionRate) >= 80 ? "text-[#22c55e]" : parseFloat(completionRate) < 60 ? "text-[#ef4444]" : ""}
          />
          <MetricItem label="Completed Runs" value={data.completed_runs.toLocaleString("en-IN")} />
          <MetricItem
            label="Running Runs"
            value={data.running_runs.toLocaleString("en-IN")}
            highlight={data.running_runs > 0}
          />
          <MetricItem
            label="Failed Runs"
            value={data.failed_runs.toLocaleString("en-IN")}
            valueClassName={data.failed_runs > 0 ? "text-[#ef4444]" : ""}
          />
          <MetricItem label="Live Alphas" value={data.live_alphas_count.toLocaleString("en-IN")} highlight />
          <MetricItem label="Running Alphas" value={data.running_alphas.toLocaleString("en-IN")} />
          <MetricItem label="Total Alpha Signals" value={data.total_alpha_signals.toLocaleString("en-IN")} />
          <MetricItem
            label="Executed Signals"
            value={`${data.executed_signals.toLocaleString("en-IN")} (${signalExecutionRate}%)`}
            highlight
          />
          <MetricItem label="Pending Signals" value={data.pending_signals.toLocaleString("en-IN")} />
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

