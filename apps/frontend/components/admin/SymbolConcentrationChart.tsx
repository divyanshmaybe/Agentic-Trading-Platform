"use client"

import { useMemo } from "react"
import { Pie } from "react-chartjs-2"
import type { ChartData } from "chart.js"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AlertTriangle } from "lucide-react"
import type { SymbolConcentration } from "@/lib/admin"
import "@/lib/chart"

type SymbolConcentrationChartProps = {
  data: SymbolConcentration[]
  title?: string
  className?: string
  loading?: boolean
}

const SYMBOL_COLORS = [
  "rgba(59,130,246,0.8)",
  "rgba(34,197,94,0.8)",
  "rgba(251,191,36,0.8)",
  "rgba(239,68,68,0.8)",
  "rgba(168,85,247,0.8)",
  "rgba(6,182,212,0.8)",
  "rgba(249,115,22,0.8)",
  "rgba(236,72,153,0.8)",
]

export function SymbolConcentrationChart({ data, title = "Symbol Concentration", className = "", loading = false }: SymbolConcentrationChartProps) {
  const chart = useMemo(() => {
    if (!data || data.length === 0) {
      return null
    }

    // Take top 10 symbols by value
    const topSymbols = [...data]
      .sort((a, b) => b.total_value - a.total_value)
      .slice(0, 10)

    const labels = topSymbols.map((d) => d.symbol)
    const values = topSymbols.map((d) => d.total_value)
    const percentages = topSymbols.map((d) => d.percentage_of_total)

    const backgroundColor = topSymbols.map((_, index) => SYMBOL_COLORS[index % SYMBOL_COLORS.length])
    const borderColor = topSymbols.map((_, index) => SYMBOL_COLORS[index % SYMBOL_COLORS.length].replace("0.8", "1"))

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

    const totalValue = values.reduce((sum, val) => sum + val, 0)
    const highConcentrationSymbols = topSymbols.filter((d) => d.percentage_of_total > 20)

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
              const index = context.dataIndex
              const symbol = labels[index]
              const value = values[index]
              const percentage = percentages[index]
              const quantity = topSymbols[index].total_quantity
              return [
                `${symbol}: ${percentage.toFixed(2)}%`,
                `Value: ₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                `Quantity: ${quantity.toLocaleString("en-IN")}`,
              ]
            },
          },
        },
      },
    }

    return { data: chartData, options, totalValue, highConcentrationSymbols }
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
        {chart.highConcentrationSymbols.length > 0 && (
          <div className="mt-2 flex items-center gap-2 rounded-lg bg-amber-500/20 px-3 py-2 text-sm text-amber-200">
            <AlertTriangle className="size-4" />
            <span>
              High concentration risk: {chart.highConcentrationSymbols.map((s) => s.symbol).join(", ")} ({">"}20%)
            </span>
          </div>
        )}
      </CardHeader>
      <CardContent>
        <div className="h-[360px] w-full rounded-xl border border-white/10 bg-black/20 p-4">
          <Pie data={chart.data} options={chart.options} />
        </div>
        <div className="mt-4 text-center text-sm text-white/60">
          Total Value: ₹{chart.totalValue.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
      </CardContent>
    </Card>
  )
}

