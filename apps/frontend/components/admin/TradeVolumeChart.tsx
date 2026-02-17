"use client"

import { useMemo } from "react"
import { Bar } from "react-chartjs-2"
import type { ChartData } from "chart.js"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { TradeVolume } from "@/lib/admin"
import "@/lib/chart"

type TradeVolumeChartProps = {
  data: TradeVolume[]
  title?: string
  className?: string
  loading?: boolean
}

export function TradeVolumeChart({ data, title = "Trade Volume Series", className = "", loading = false }: TradeVolumeChartProps) {
  const chart = useMemo(() => {
    if (!data || data.length === 0) {
      return null
    }

    const labels = data.map((d) => {
      const date = new Date(d.date)
      return date.toLocaleDateString("en-IN", { month: "short", day: "numeric" })
    })
    const buyCounts = data.map((d) => d.buy_count)
    const sellCounts = data.map((d) => d.sell_count)
    const totalCounts = data.map((d) => d.trade_count)

    const chartData: ChartData<"bar"> = {
      labels,
      datasets: [
        {
          label: "Buy",
          data: buyCounts,
          backgroundColor: "rgba(34,197,94,0.8)",
          borderColor: "#22c55e",
          borderWidth: 1,
          borderRadius: 4,
        },
        {
          label: "Sell",
          data: sellCounts,
          backgroundColor: "rgba(239,68,68,0.8)",
          borderColor: "#ef4444",
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
              const value = context.parsed.y
              const total = totalCounts[index]
              const volume = data[index].total_volume
              return [
                `${context.dataset.label}: ${value}`,
                `Total: ${total}`,
                `Volume: ₹${volume.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
              ]
            },
          },
        },
      },
      interaction: { mode: "index" as const, intersect: false },
      scales: {
        x: {
          stacked: true,
          grid: { display: false },
          ticks: { color: "#9CA3AF", maxRotation: 45, minRotation: 45 },
        },
        y: {
          stacked: true,
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: {
            color: "#9CA3AF",
            callback: (value: any) => (value as number).toLocaleString("en-IN"),
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

