import { useMemo } from "react"
import { Pie } from "react-chartjs-2"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import type { PortfolioSummary } from "@/lib/dashboardTypes"
import { formatCurrency } from "@/lib/dashboardData"
import { cn } from "@/lib/utils"

import { allocationChartOptions, createAllocationChartData, pieDepthPlugin } from "./chartConfig"

type PortfolioOverviewCardProps = {
  summary: PortfolioSummary
  loading?: boolean
}

export function PortfolioOverviewCard({ summary, loading = false }: PortfolioOverviewCardProps) {
  const hasAllocations = summary.allocation && summary.allocation.length > 0
  const allocationChart = useMemo(() => createAllocationChartData(summary.allocation), [summary.allocation])
  const formatted = useMemo(() => {
    const changePositive = summary.changeValue >= 0

    return {
      totalValue: formatCurrency(summary.totalValue),
      investmentAmount: formatCurrency(summary.investmentAmount),
      availableCash: formatCurrency(summary.availableCash),
      changeValue: Math.abs(summary.changeValue).toLocaleString("en-US"),
      changePrefix: changePositive ? "+" : "-",
      changePctPrefix: summary.changePct > 0 ? "+" : summary.changePct < 0 ? "-" : "",
      riskTolerance: summary.riskTolerance.charAt(0).toUpperCase() + summary.riskTolerance.slice(1),
    }
  }, [summary])

  return (
    <Card className="card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur">
      <CardHeader className="gap-2">
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Portfolio Overview
        </CardDescription>
        <CardTitle className="h-title text-2xl text-[#fafafa]">
          {loading ? (
            <div className="h-8 w-48 animate-pulse rounded bg-white/10" />
          ) : (
            formatted.availableCash
          )}
        </CardTitle>

      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div className="grid gap-4">
          <div className="grid grid-cols-1 gap-4 text-sm text-white/70 sm:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Invested Amount</span>
              {loading ? (
                <div className="mt-2 h-6 w-24 animate-pulse rounded bg-white/10" />
              ) : (
                <p className="mt-2 text-lg font-semibold text-[#fafafa]">
                  {formatted.investmentAmount}
                </p>
              )}
            </div>
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Total Return</span>
              {loading ? (
                <div className="mt-2 h-6 w-32 animate-pulse rounded bg-white/10" />
              ) : (
                <p
                  className={cn(
                    "mt-2 text-lg font-semibold",
                    summary.changeValue >= 0 ? "text-[#22c55e]" : "text-[#ef4444]",
                  )}
                >
                  {formatted.changePctPrefix}
                  {Math.abs(summary.changePct).toFixed(2)}% ({formatted.changePrefix}$
                  {formatted.changeValue})
                </p>
              )}
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/8 p-4 text-sm text-white/70">
            <span className="text-xs uppercase tracking-[0.3em] text-white/45">Portfolio Details</span>
            {loading ? (
              <div className="mt-3 space-y-2">
                <div className="h-4 w-full animate-pulse rounded bg-white/10" />
                <div className="h-4 w-3/4 animate-pulse rounded bg-white/10" />
                <div className="h-4 w-5/6 animate-pulse rounded bg-white/10" />
              </div>
            ) : (
              <div className="mt-3 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <span className="text-white/60">Portfolio Name</span>
                  <span className="font-semibold text-[#fafafa]">{summary.portfolioName}</span>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <span className="text-white/60">Risk Tolerance</span>
                  <span className="font-semibold text-[#fafafa]">{formatted.riskTolerance}</span>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <span className="text-white/60">Expected Return</span>
                  <span className="font-semibold text-[#fafafa]">{summary.expectedReturn.toFixed(1)}%</span>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <span className="text-white/60">Investment Horizon</span>
                  <span className="font-semibold text-[#fafafa]">
                    {summary.investmentHorizon} {summary.investmentHorizon === 1 ? "year" : "years"}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center justify-center">
          {loading ? (
            <div className="w-full max-w-xs">
              <div className="h-64 w-64 animate-pulse rounded-full bg-white/10" />
            </div>
          ) : hasAllocations ? (
            <div className="w-full max-w-xs">
              <Pie data={allocationChart} options={allocationChartOptions} plugins={[pieDepthPlugin]} />
            </div>
          ) : (
            <div className="flex w-full flex-col items-center justify-center space-y-4 rounded-xl border border-amber-500/20 bg-gradient-to-br from-amber-500/10 to-orange-500/5 p-8 text-center">
              <div className="relative">
                <div className="h-16 w-16 animate-spin rounded-full border-4 border-white/10 border-t-amber-400" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="h-8 w-8 rounded-full bg-amber-400/20" />
                </div>
              </div>
              <div className="space-y-2">
                <h4 className="text-base font-semibold text-amber-200">Balancing Portfolio</h4>
                <p className="text-xs leading-relaxed text-white/60">
                  We're currently balancing your investments between long-term, intraday, and algorithmic trading strategies.
                </p>
              </div>
              <div className="flex flex-col space-y-2 text-xs text-white/45">
                <div className="flex items-center space-x-2">
                  <div className="h-2 w-2 animate-pulse rounded-full bg-amber-400" />
                  <span>Analyzing risk profile...</span>
                </div>
                <div className="flex items-center space-x-2">
                  <div className="h-2 w-2 animate-pulse rounded-full bg-amber-400 [animation-delay:200ms]" />
                  <span>Optimizing allocations...</span>
                </div>
                <div className="flex items-center space-x-2">
                  <div className="h-2 w-2 animate-pulse rounded-full bg-amber-400 [animation-delay:400ms]" />
                  <span>Configuring strategies...</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

