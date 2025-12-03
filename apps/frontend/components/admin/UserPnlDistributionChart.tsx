"use client"

import { useMemo } from "react"
import { Bar } from "react-chartjs-2"
import type { ChartData } from "chart.js"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { PnlBucket } from "@/lib/admin"
import "@/lib/chart"

type UserPnlDistributionChartProps = {
  data: PnlBucket[]
  title?: string
  className?: string
  loading?: boolean
}

export function UserPnlDistributionChart({ data, title = "User P&L Distribution", className = "", loading = false }: UserPnlDistributionChartProps) {
  const chart = useMemo(() => {
    if (!data || data.length === 0) {
      return null
    }

    // Sort by range_min to maintain order
    const sortedData = [...data].sort((a, b) => a.range_min - b.range_min)

    const labels = sortedData.map((d) => d.range_label)
    const userCounts = sortedData.map((d) => d.user_count)
    const totalPnl = sortedData.map((d) => d.total_pnl)

    // Color bars based on positive/negative ranges
    const backgroundColors = sortedData.map((d) => {
      if (d.range_max < 0) return "rgba(239,68,68,0.8)"
      if (d.range_min > 0) return "rgba(34,197,94,0.8)"
      return "rgba(156,163,175,0.8)" // neutral/zero range
    })

    const chartData: ChartData<"bar"> = {
      labels,
      datasets: [
        {
          label: "User Count",
          data: userCounts,
          backgroundColor: backgroundColors,
          borderColor: sortedData.map((d) => {
            if (d.range_max < 0) return "#ef4444"
            if (d.range_min > 0) return "#22c55e"
            return "#9ca3af"
          }),
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
              const count = userCounts[index]
              const pnl = totalPnl[index]
              return [
                `Users: ${count.toLocaleString("en-IN")}`,
                `Total P&L: ₹${pnl.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
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

