"use client"

import { useMemo } from "react"
import { Line } from "react-chartjs-2"
import type { ChartData, ScriptableContext } from "chart.js"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { MonthlyPnl } from "@/lib/admin"
import "@/lib/chart"

type MonthlyPnlChartProps = {
  data: MonthlyPnl[]
  title?: string
  className?: string
  loading?: boolean
}

const gradientFill = (from: string, to: string) =>
  (context: ScriptableContext<"line">) => {
    const { ctx, chartArea } = context.chart
    if (!chartArea) {
      return from
    }

    const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top)
    gradient.addColorStop(0, from)
    gradient.addColorStop(1, to)
    return gradient
  }

export function MonthlyPnlChart({ data, title = "Monthly P&L", className = "", loading = false }: MonthlyPnlChartProps) {
  const chart = useMemo(() => {
    if (!data || data.length === 0) {
      return null
    }

    const labels = data.map((d) => d.month)
    const cumulativePnl = data.map((d) => d.cumulative_pnl)
    const monthlyPnl = data.map((d) => d.realized_pnl)

    const isPositive = cumulativePnl.length > 0 && cumulativePnl[cumulativePnl.length - 1] >= cumulativePnl[0]
    const palette = isPositive
      ? {
          border: "#22c55e",
          gradientFrom: "rgba(34,197,94,0.2)",
          gradientTo: "rgba(34,197,94,0)",
        }
      : {
          border: "#ef4444",
          gradientFrom: "rgba(239,68,68,0.2)",
          gradientTo: "rgba(239,68,68,0)",
        }

    const chartData: ChartData<"line"> = {
      labels,
      datasets: [
        {
          label: "Cumulative P&L",
          data: cumulativePnl,
          borderColor: palette.border,
          backgroundColor: gradientFill(palette.gradientFrom, palette.gradientTo),
          borderWidth: 2,
          tension: 0.35,
          fill: true,
          pointRadius: 0,
          borderCapStyle: "round",
          borderJoinStyle: "round",
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
          callbacks: {
            label: (context: any) => {
              const index = context.dataIndex
              const monthly = monthlyPnl[index]
              const cumulative = cumulativePnl[index]
              return [
                `Monthly: ₹${monthly.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                `Cumulative: ₹${cumulative.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
              ]
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

