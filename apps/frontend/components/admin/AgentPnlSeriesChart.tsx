"use client"

import { useMemo } from "react"
import { Line } from "react-chartjs-2"
import type { ChartData, ScriptableContext } from "chart.js"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { AgentSnapshot } from "@/lib/admin"
import "@/lib/chart"

type AgentPnlSeriesChartProps = {
  data: AgentSnapshot[]
  title?: string
  className?: string
  loading?: boolean
}

const AGENT_COLORS = [
  "#3b82f6",
  "#22c55e",
  "#fbbf24",
  "#ef4444",
  "#a855f7",
  "#06b6d4",
  "#f97316",
  "#ec4899",
]

const gradientFill = (color: string) =>
  (context: ScriptableContext<"line">) => {
    const { ctx, chartArea } = context.chart
    if (!chartArea) {
      return color
    }

    const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top)
    gradient.addColorStop(0, color.replace("rgb", "rgba").replace(")", ",0.2)"))
    gradient.addColorStop(1, color.replace("rgb", "rgba").replace(")", ",0)"))
    return gradient
  }

export function AgentPnlSeriesChart({ data, title = "Agent P&L Series", className = "", loading = false }: AgentPnlSeriesChartProps) {
  const chart = useMemo(() => {
    if (!data || data.length === 0) {
      return null
    }

    // Group by agent_type and sort by snapshot_at
    const grouped = data.reduce((acc, snapshot) => {
      if (!acc[snapshot.agent_type]) {
        acc[snapshot.agent_type] = []
      }
      acc[snapshot.agent_type].push(snapshot)
      return acc
    }, {} as Record<string, AgentSnapshot[]>)

    // Sort each group by time
    Object.keys(grouped).forEach((type) => {
      grouped[type].sort((a, b) => new Date(a.snapshot_at).getTime() - new Date(b.snapshot_at).getTime())
    })

    // Get all unique timestamps
    const allTimestamps = Array.from(new Set(data.map((d) => d.snapshot_at))).sort(
      (a, b) => new Date(a).getTime() - new Date(b).getTime()
    )

    const labels = allTimestamps.map((ts) => {
      const date = new Date(ts)
      return date.toLocaleDateString("en-IN", { month: "short", day: "numeric" })
    })

    const agentTypes = Object.keys(grouped)
    const datasets = agentTypes.map((type, index) => {
      const snapshots = grouped[type]
      const pnlData = allTimestamps.map((ts) => {
        const snapshot = snapshots.find((s) => s.snapshot_at === ts)
        return snapshot?.realized_pnl || null
      })

      const color = AGENT_COLORS[index % AGENT_COLORS.length]
      const typeMap: Record<string, string> = {
        nse_signal: "NSE Signal",
        low_risk: "Low Risk",
        high_risk: "High Risk",
        alpha: "Alpha Copilot",
        liquid: "Liquidity",
      }

      return {
        label: typeMap[type] || type,
        data: pnlData,
        borderColor: color,
        backgroundColor: gradientFill(color),
        borderWidth: 2,
        tension: 0.35,
        fill: false,
        pointRadius: 2,
        pointHoverRadius: 4,
      }
    })

    const chartData: ChartData<"line"> = {
      labels,
      datasets,
    }

    const options = {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 700, easing: "easeOutQuart" as const },
      plugins: {
        legend: {
          labels: {
            color: "#E5E5E5",
          },
        },
        tooltip: {
          mode: "index" as const,
          intersect: false,
          backgroundColor: "rgba(22,26,30,0.95)",
          borderColor: "#1f2937",
          borderWidth: 1,
          titleColor: "#E5E5E5",
          bodyColor: "#9CA3AF",
          callbacks: {
            label: (context: any) => {
              const value = context.parsed.y
              if (value === null) return `${context.dataset.label}: No data`
              return `${context.dataset.label}: ₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            },
          },
        },
      },
      interaction: { mode: "nearest" as const, intersect: false },
      scales: {
        x: {
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: { color: "#9CA3AF" },
        },
        y: {
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: {
            color: "#9CA3AF",
            callback: (value: any) => `₹${(value as number).toLocaleString("en-IN")}`,
          },
        },
      },
    }

    return { data: chartData, options }
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

  if (!chart || !data || data.length === 0) {
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
        <div className="h-[360px] w-full rounded-xl border border-white/10 bg-black/20 p-2">
          <Line data={chart.data} options={chart.options} />
        </div>
      </CardContent>
    </Card>
  )
}

