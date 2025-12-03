"use client"

import { useMemo } from "react"
import { Bar } from "react-chartjs-2"
import type { ChartData } from "chart.js"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { AgentMetrics } from "@/lib/admin"
import "@/lib/chart"

type AgentMetricsChartProps = {
  data: AgentMetrics[]
  title?: string
  className?: string
  loading?: boolean
}

export function AgentMetricsChart({ data, title = "Agent Metrics by Type", className = "", loading = false }: AgentMetricsChartProps) {
  const chart = useMemo(() => {
    if (!data || data.length === 0) {
      return null
    }

    const labels = data.map((d) => {
      const typeMap: Record<string, string> = {
        nse_signal: "NSE Signal",
        low_risk: "Low Risk",
        high_risk: "High Risk",
        alpha: "Alpha Copilot",
        liquid: "Liquidity",
      }
      return typeMap[d.agent_type] || d.agent_type
    })

    const pnlData = data.map((d) => d.total_realized_pnl)
    const tradeData = data.map((d) => d.total_trades)
    const winRateData = data.map((d) => d.win_rate_percentage)

    const chartData: ChartData<"bar"> = {
      labels,
      datasets: [
        {
          label: "Total P&L (₹)",
          data: pnlData,
          backgroundColor: "rgba(59,130,246,0.8)",
          borderColor: "#3b82f6",
          borderWidth: 1,
          borderRadius: 4,
          yAxisID: "y",
        },
        {
          label: "Total Trades",
          data: tradeData,
          backgroundColor: "rgba(34,197,94,0.8)",
          borderColor: "#22c55e",
          borderWidth: 1,
          borderRadius: 4,
          yAxisID: "y1",
        },
        {
          label: "Win Rate (%)",
          data: winRateData,
          backgroundColor: "rgba(251,191,36,0.8)",
          borderColor: "#fbbf24",
          borderWidth: 1,
          borderRadius: 4,
          yAxisID: "y2",
        },
      ],
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
        },
      },
      interaction: { mode: "index" as const, intersect: false },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#9CA3AF" },
        },
        y: {
          type: "linear" as const,
          display: true,
          position: "left" as const,
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: {
            color: "#9CA3AF",
            callback: (value: any) => `₹${(value as number).toLocaleString("en-IN")}`,
          },
        },
        y1: {
          type: "linear" as const,
          display: false,
          position: "right" as const,
          grid: { drawOnChartArea: false },
        },
        y2: {
          type: "linear" as const,
          display: false,
          position: "right" as const,
          grid: { drawOnChartArea: false },
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
          <Bar data={chart.data} options={chart.options} />
        </div>
      </CardContent>
    </Card>
  )
}

