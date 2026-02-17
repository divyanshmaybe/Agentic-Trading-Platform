import { useMemo, useRef, useEffect } from "react"
import { Pie } from "react-chartjs-2"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import type { PortfolioSummary } from "@/lib/dashboardTypes"
import { formatCurrency } from "@/lib/dashboardData"
import { cn } from "@/lib/utils"
import { AllocationLoadingState } from "@/components/shared/AllocationLoadingState"
import { NoAllocationsState } from "./NoAllocationsState"

import { allocationChartOptions, createAllocationChartData, pieDepthPlugin } from "./chartConfig"

type PortfolioOverviewCardProps = {
  summary: PortfolioSummary
  loading?: boolean
}

export function PortfolioOverviewCard({ summary, loading = false }: PortfolioOverviewCardProps) {
  const hasAllocations = summary.allocation && summary.allocation.length > 0
  const hasEverLoadedPortfolioRef = useRef(false)
  
  // Track if we've ever successfully loaded portfolio data - once true, never show "Balancing Portfolio" again
  useEffect(() => {
    // If we're not loading and we have portfolio data (even if allocations are empty), mark as loaded
    if (!loading && summary.portfolioName !== "No Portfolio") {
      hasEverLoadedPortfolioRef.current = true
    }
  }, [loading, summary.portfolioName])
  
  // Only show "Balancing Portfolio" if we've never loaded portfolio data and we're not currently loading
  const shouldShowBalancing = !hasEverLoadedPortfolioRef.current && !loading && !hasAllocations
  const allocationChart = useMemo(() => createAllocationChartData(summary.allocation), [summary.allocation])
  
  const formatted = useMemo(() => {
    // Use backend-calculated values (GROUND TRUTH from snapshot_service formula)
    const currentValue = summary.currentValue
    const totalPnl = summary.totalPnl
    const totalReturnPct = summary.totalReturnPct
    const unrealizedPnl = summary.totalUnrealizedPnl
    
    const changePositive = totalPnl >= 0

    return {
      totalValue: formatCurrency(summary.currentValue),
      investmentAmount: formatCurrency(summary.investmentAmount),
      availableCash: formatCurrency(summary.availableCash),
      currentPortfolioValue: formatCurrency(currentValue),
      realizedPnL: summary.changeValue, // Keep for backward compatibility
      realizedPnLFormatted: formatCurrency(summary.changeValue),
      unrealizedPnL: unrealizedPnl,
      unrealizedPnLFormatted: formatCurrency(unrealizedPnl),
      totalPnL: Math.abs(totalPnl),
      totalPnLFormatted: formatCurrency(Math.abs(totalPnl)),
      totalPnLPct: Math.abs(totalReturnPct).toFixed(2),
      changeValue: Math.abs(summary.changeValue).toLocaleString("en-IN"),
      changePrefix: changePositive ? "+" : "-",
      changePctPrefix: totalPnl > 0 ? "+" : totalPnl < 0 ? "-" : "",
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
            formatted.currentPortfolioValue
          )}
        </CardTitle>

      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div className="grid gap-4">
          <div className="grid grid-cols-1 gap-4 text-sm text-white/70 sm:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Initial Investment</span>
              {loading ? (
                <div className="mt-2 h-6 w-24 animate-pulse rounded bg-white/10" />
              ) : (
                <p className="mt-2 text-lg font-semibold text-[#fafafa]">
                  {formatted.investmentAmount}
                </p>
              )}
            </div>
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Total P&L</span>
              {loading ? (
                <div className="mt-2 h-6 w-32 animate-pulse rounded bg-white/10" />
              ) : (
                <p
                  className={cn(
                    "mt-2 text-lg font-semibold",
                    formatted.changePrefix === "+" ? "text-[#22c55e]" : "text-[#ef4444]",
                  )}
                >
                  {formatted.changePctPrefix}
                  {formatted.totalPnLPct}% ({formatted.changePrefix}₹
                  {formatted.totalPnLFormatted})
                </p>
              )}
            </div>
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Realized P&L</span>
              {loading ? (
                <div className="mt-2 h-6 w-24 animate-pulse rounded bg-white/10" />
              ) : (
                <p className={cn(
                  "mt-2 text-lg font-semibold",
                  formatted.realizedPnL >= 0 ? "text-[#22c55e]" : "text-[#ef4444]",
                )}>
                  {formatted.realizedPnLFormatted}
                </p>
              )}
            </div>
            <div className="rounded-xl border border-white/10 bg-white/8 p-4">
              <span className="text-xs uppercase tracking-[0.3em] text-white/45">Unrealized P&L</span>
              {loading ? (
                <div className="mt-2 h-6 w-24 animate-pulse rounded bg-white/10" />
              ) : (
                <p className={cn(
                  "mt-2 text-lg font-semibold",
                  formatted.unrealizedPnL >= 0 ? "text-[#22c55e]" : "text-[#ef4444]",
                )}>
                  {formatted.unrealizedPnLFormatted}
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
          ) : shouldShowBalancing ? (
            <AllocationLoadingState
              title="Balancing Portfolio"
              description="We're currently balancing your investments between long-term, intraday, and algorithmic trading strategies."
              steps={[
                "Analyzing risk profile...",
                "Optimizing allocations...",
                "Configuring strategies...",
              ]}
              className="w-full"
            />
          ) : hasAllocations ? (
            <div className="w-full max-w-xs">
              <Pie data={allocationChart} options={allocationChartOptions} plugins={[pieDepthPlugin]} />
            </div>
          ) : (
            // If we've had allocations before but they're empty now, show empty state instead of "Balancing Portfolio"
            <NoAllocationsState />
          )}
        </div>
      </CardContent>
    </Card>
  )
}

