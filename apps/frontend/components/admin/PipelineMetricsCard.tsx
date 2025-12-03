"use client"

import type { ComponentPropsWithoutRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { PipelineMetrics } from "@/lib/admin"

type PipelineMetricsCardProps = {
  data: PipelineMetrics | null
  title?: string
  className?: string
  loading?: boolean
} & ComponentPropsWithoutRef<typeof Card>

function formatMs(ms: number | null | undefined): string {
  if (ms == null || isNaN(ms)) return "N/A"
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function PipelineMetricsCard({ data, title = "Pipeline Metrics (NSE Signal)", className = "", loading = false, ...cardProps }: PipelineMetricsCardProps) {
  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {Array.from({ length: 8 }).map((_, i) => (
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
          <MetricItem label="Signals Today" value={data.signals_today.toLocaleString("en-IN")} highlight />
          <MetricItem label="Signals This Week" value={data.signals_this_week.toLocaleString("en-IN")} />
          <MetricItem label="Avg LLM Delay" value={formatMs(data.avg_llm_delay_ms)} />
          <MetricItem label="Avg Trade Delay" value={formatMs(data.avg_trade_delay_ms)} />
          <MetricItem label="Min LLM Delay" value={formatMs(data.min_llm_delay_ms)} />
          <MetricItem label="Max LLM Delay" value={formatMs(data.max_llm_delay_ms)} />
          <MetricItem label="Min Trade Delay" value={formatMs(data.min_trade_delay_ms)} />
          <MetricItem label="Max Trade Delay" value={formatMs(data.max_trade_delay_ms)} />
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

