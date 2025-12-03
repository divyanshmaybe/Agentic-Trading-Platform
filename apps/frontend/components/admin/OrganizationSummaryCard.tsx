"use client"

import type { ComponentPropsWithoutRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { OrganizationSummary } from "@/lib/admin"
import { formatCurrency } from "@/lib/admin"

type OrganizationSummaryCardProps = {
  data: OrganizationSummary | null
  title?: string
  className?: string
  loading?: boolean
} & ComponentPropsWithoutRef<typeof Card>

export function OrganizationSummaryCard({ data, title = "Organization Summary", className = "", loading = false, ...cardProps }: OrganizationSummaryCardProps) {
  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {Array.from({ length: 7 }).map((_, i) => (
              <div key={i} className="h-20 animate-pulse rounded-xl bg-white/5" />
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!data) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-48 items-center justify-center text-white/60">No data available</div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <MetricItem label="Total Portfolios" value={data.total_portfolios.toLocaleString("en-IN")} />
          <MetricItem label="Active Portfolios" value={data.active_portfolios.toLocaleString("en-IN")} />
          <MetricItem label="Total Users" value={data.total_users.toLocaleString("en-IN")} />
          <MetricItem label="Active Users" value={data.active_users.toLocaleString("en-IN")} />
          <MetricItem label="Total AUM" value={formatCurrency(data.total_aum)} />
          <MetricItem label="Available Cash" value={formatCurrency(data.total_available_cash)} />
          <MetricItem label="Total Invested" value={formatCurrency(data.total_invested)} className="sm:col-span-2" />
        </div>
      </CardContent>
    </Card>
  )
}

function MetricItem({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className={`rounded-xl border border-white/10 bg-white/5 p-4 ${className}`}>
      <div className="text-xs text-white/60">{label}</div>
      <div className="mt-1 text-lg font-semibold text-[#fafafa]">{value}</div>
    </div>
  )
}

