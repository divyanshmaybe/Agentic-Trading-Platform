import { useMemo } from "react"
import { Pie } from "react-chartjs-2"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import type { PortfolioSummary } from "@/lib/dashboardTypes"
import { formatCurrency } from "@/lib/dashboardData"
import { cn } from "@/lib/utils"

import { allocationChartOptions, createAllocationChartData, pieDepthPlugin } from "./chartConfig"

type PortfolioOverviewCardProps = {
  summary: PortfolioSummary
}

export function PortfolioOverviewCard({ summary }: PortfolioOverviewCardProps) {
  const allocationChart = useMemo(() => createAllocationChartData(summary.allocation), [summary.allocation])
  const formatted = useMemo(() => {
    const dailyPositive = summary.dailyPnL >= 0
    const changePositive = summary.changeValue >= 0

    return {
      totalValue: formatCurrency(summary.totalValue),
      dailyPnL: Math.abs(summary.dailyPnL).toLocaleString("en-US"),
      dailyPrefix: dailyPositive ? "+" : "-",
      changeValue: Math.abs(summary.changeValue).toLocaleString("en-US"),
      changePrefix: changePositive ? "+" : "-",
      changePctPrefix: summary.changePct > 0 ? "+" : summary.changePct < 0 ? "-" : "",
    }
  }, [summary])

  return (
    <Card className="card-glass neon-hover rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur">
      <CardHeader className="gap-2">
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Portfolio Overview
        </CardDescription>
        <CardTitle className="h-title text-2xl text-[#fafafa]">{formatted.totalValue}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div className="grid gap-4">
          <div className="grid grid-cols-2 gap-4 text-sm text-white/70">
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Day Change</span>
              <p
                className={cn(
                  "mt-2 text-lg font-semibold",
                  formatted.dailyPrefix === "+" ? "text-[#22c55e]" : "text-[#ef4444]",
                )}
              >
                {formatted.dailyPrefix}${formatted.dailyPnL}
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Total Delta</span>
              <p className="mt-2 text-lg font-semibold text-[#fafafa]">
                {formatted.changePctPrefix}
                {Math.abs(summary.changePct).toFixed(2)}% ({formatted.changePrefix}${formatted.changeValue})
              </p>
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/8 p-4 text-sm text-white/70">
            <span className="text-xs uppercase tracking-[0.3em] text-white/45">Insight</span>
            <p className="mt-2 leading-relaxed">
              Alpha sleeve outpaces benchmark this session. Liquidity buffers remain within target bands and VaR is holding at 0.8%.
            </p>
          </div>
        </div>
        <div className="flex items-center justify-center">
          <div className="w-full max-w-xs">
            <Pie data={allocationChart} options={allocationChartOptions} plugins={[pieDepthPlugin]} />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

