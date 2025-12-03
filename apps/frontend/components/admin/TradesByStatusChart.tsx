"use client"

import { useMemo } from "react"
import { Pie } from "react-chartjs-2"
import type { ChartData } from "chart.js"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { TradesByStatus } from "@/lib/admin"
import "@/lib/chart"

type TradesByStatusChartProps = {
  data: TradesByStatus | null | undefined
  title?: string
  className?: string
  loading?: boolean
}

const STATUS_COLORS = {
  executed: "rgba(34,197,94,0.8)",
  pending: "rgba(251,191,36,0.8)",
  pending_tp: "rgba(59,130,246,0.8)",
  pending_sl: "rgba(239,68,68,0.8)",
  cancelled: "rgba(156,163,175,0.8)",
  failed: "rgba(239,68,68,0.8)",
}

const STATUS_BORDER_COLORS = {
  executed: "#22c55e",
  pending: "#fbbf24",
  pending_tp: "#3b82f6",
  pending_sl: "#ef4444",
  cancelled: "#9ca3af",
  failed: "#ef4444",
}

const STATUS_LABELS = {
  executed: "Executed",
  pending: "Pending",
  pending_tp: "Pending TP",
  pending_sl: "Pending SL",
  cancelled: "Cancelled",
  failed: "Failed",
}

export function TradesByStatusChart({ data, title = "Trades by Status", className = "", loading = false }: TradesByStatusChartProps) {
  const chart = useMemo(() => {
    if (!data) {
      return null
    }

    const entries = Object.entries(data).filter(([_, value]) => value > 0)
    if (entries.length === 0) {
      return null
    }

    const labels = entries.map(([key]) => STATUS_LABELS[key as keyof typeof STATUS_LABELS])
    const values = entries.map(([_, value]) => value)
    const keys = entries.map(([key]) => key)

    const backgroundColor = keys.map((key) => STATUS_COLORS[key as keyof typeof STATUS_COLORS])
    const borderColor = keys.map((key) => STATUS_BORDER_COLORS[key as keyof typeof STATUS_BORDER_COLORS])

    const chartData: ChartData<"pie"> = {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor,
          borderColor,
          borderWidth: 2,
        },
      ],
    }

    const total = values.reduce((sum, val) => sum + val, 0)

    const options = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "right" as const,
          labels: {
            color: "#E5E5E5",
            padding: 15,
            usePointStyle: true,
          },
        },
        tooltip: {
          backgroundColor: "rgba(22,26,30,0.95)",
          borderColor: "#1f2937",
          borderWidth: 1,
          titleColor: "#E5E5E5",
          bodyColor: "#9CA3AF",
          callbacks: {
            label: (context: any) => {
              const label = context.label || ""
              const value = context.parsed || 0
              const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : "0"
              return `${label}: ${value.toLocaleString("en-IN")} (${percentage}%)`
            },
          },
        },
      },
    }

    return { data: chartData, options, total }
  }, [data])

  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[360px] w-full animate-pulse rounded-xl bg-white/5" />
        </CardContent>
      </Card>
    )
  }

  if (!chart || !data) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-[360px] items-center justify-center text-white/60">No data available</div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`}>
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[360px] w-full rounded-xl border border-white/10 bg-black/20 p-4">
          <Pie data={chart.data} options={chart.options} />
        </div>
        <div className="mt-4 text-center text-sm text-white/60">
          Total: {chart.total.toLocaleString("en-IN")} trades
        </div>
      </CardContent>
    </Card>
  )
}

