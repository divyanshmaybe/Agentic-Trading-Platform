"use client"

import { useMemo } from "react"
import { Bar } from "react-chartjs-2"
import type { ChartData } from "chart.js"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { HourlyDistribution } from "@/lib/admin"
import "@/lib/chart"

type HourlyTradeHeatmapProps = {
  data: HourlyDistribution[]
  title?: string
  className?: string
  loading?: boolean
}

export function HourlyTradeHeatmap({ data, title = "Hourly Trade Distribution", className = "", loading = false }: HourlyTradeHeatmapProps) {
  const chart = useMemo(() => {
    if (!data || data.length === 0) {
      return null
    }

    // Create array for all 24 hours
    const hourlyData = Array.from({ length: 24 }, (_, hour) => {
      const hourData = data.find((d) => d.hour === hour)
      return {
        hour,
        trade_count: hourData?.trade_count || 0,
        volume: hourData?.volume || 0,
      }
    })

    const labels = hourlyData.map((d) => `${d.hour.toString().padStart(2, "0")}:00`)
    const tradeCounts = hourlyData.map((d) => d.trade_count)
    const volumes = hourlyData.map((d) => d.volume)

    const maxTradeCount = Math.max(...tradeCounts, 1)
    const backgroundColors = tradeCounts.map((count) => {
      const intensity = count / maxTradeCount
      return `rgba(59,130,246,${0.3 + intensity * 0.7})`
    })

    const chartData: ChartData<"bar"> = {
      labels,
      datasets: [
        {
          label: "Trade Count",
          data: tradeCounts,
          backgroundColor: backgroundColors,
          borderColor: "#3b82f6",
          borderWidth: 1,
          borderRadius: 2,
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
              const count = tradeCounts[index]
              const volume = volumes[index]
              return [
                `Trades: ${count.toLocaleString("en-IN")}`,
                `Volume: ₹${volume.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
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

