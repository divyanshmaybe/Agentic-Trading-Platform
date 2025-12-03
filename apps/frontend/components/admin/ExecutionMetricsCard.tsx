"use client"

import type { ComponentPropsWithoutRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ExecutionMetrics } from "@/lib/admin"

type ExecutionMetricsCardProps = {
  data: ExecutionMetrics | null
  title?: string
  className?: string
  loading?: boolean
} & ComponentPropsWithoutRef<typeof Card>

function formatMs(ms: number | null | undefined): string {
  if (ms == null || isNaN(ms)) return "N/A"
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function ExecutionMetricsCard({ data, title = "Execution Metrics", className = "", loading = false, ...cardProps }: ExecutionMetricsCardProps) {
  const successRate = data && data.total_executions > 0
    ? ((data.successful_executions / data.total_executions) * 100).toFixed(2)
    : "0"

  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {Array.from({ length: 5 }).map((_, i) => (
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
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <MetricItem label="Total Executions" value={data.total_executions.toLocaleString("en-IN")} />
          <MetricItem
            label="Success Rate"
            value={`${successRate}%`}
            highlight={parseFloat(successRate) >= 95}
            valueClassName={parseFloat(successRate) >= 95 ? "text-[#22c55e]" : parseFloat(successRate) < 90 ? "text-[#ef4444]" : ""}
          />
          <MetricItem label="Successful Executions" value={data.successful_executions.toLocaleString("en-IN")} />
          <MetricItem
            label="Failed Executions"
            value={data.failed_executions.toLocaleString("en-IN")}
            valueClassName={data.failed_executions > 0 ? "text-[#ef4444]" : ""}
          />
          <MetricItem label="Pending Executions" value={data.pending_executions.toLocaleString("en-IN")} />
          <MetricItem label="Avg Execution Time" value={formatMs(data.avg_execution_time_ms)} highlight />
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

