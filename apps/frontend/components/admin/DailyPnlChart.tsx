"use client"

import { useMemo } from "react"
import { Bar } from "react-chartjs-2"
import type { ChartData } from "chart.js"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { DailyPnl } from "@/lib/admin"
import "@/lib/chart"

type DailyPnlChartProps = {
  data: DailyPnl[]
  title?: string
  className?: string
  loading?: boolean
}

export function DailyPnlChart({ data, title = "Daily P&L (Last 30 Days)", className = "", loading = false }: DailyPnlChartProps) {
  const chart = useMemo(() => {
    if (!data || data.length === 0) {
      return null
    }

    const labels = data.map((d) => {
      const date = new Date(d.date)
      return date.toLocaleDateString("en-IN", { month: "short", day: "numeric" })
    })
    const pnlValues = data.map((d) => d.realized_pnl)
    const tradeCounts = data.map((d) => d.trade_count)

    const backgroundColors = pnlValues.map((pnl) => (pnl >= 0 ? "rgba(34,197,94,0.8)" : "rgba(239,68,68,0.8)"))

    const chartData: ChartData<"bar"> = {
      labels,
      datasets: [
        {
          label: "Realized P&L",
          data: pnlValues,
          backgroundColor: backgroundColors,
          borderColor: pnlValues.map((pnl) => (pnl >= 0 ? "#22c55e" : "#ef4444")),
          borderWidth: 1,
          borderRadius: 4,
        },
      ],
    }

    const options = {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 700, easing: "easeOutQuart" as const },
      plugins: {
        legend: {
          display: false,
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
              const index = context.dataIndex
              const pnl = pnlValues[index]
              const trades = tradeCounts[index]
              return [
                `P&L: ₹${pnl.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                `Trades: ${trades}`,
              ]
            },
          },
        },
      },
      interaction: { mode: "index" as const, intersect: false },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#9CA3AF", maxRotation: 45, minRotation: 45 },
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
          <Bar data={chart.data} options={chart.options} />
        </div>
      </CardContent>
    </Card>
  )
}

