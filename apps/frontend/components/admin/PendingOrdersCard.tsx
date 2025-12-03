"use client"

import type { ComponentPropsWithoutRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AlertTriangle } from "lucide-react"
import type { PendingOrders } from "@/lib/admin"
import { formatCurrency } from "@/lib/admin"

type PendingOrdersCardProps = {
  data: PendingOrders | null
  title?: string
  className?: string
  loading?: boolean
} & ComponentPropsWithoutRef<typeof Card>

export function PendingOrdersCard({ data, title = "Pending Orders", className = "", loading = false, ...cardProps }: PendingOrdersCardProps) {
  const totalPending = data
    ? data.pending_limit_orders + data.pending_stop_loss + data.pending_take_profit + data.pending_auto_sell
    : 0
  const hasHighPending = totalPending > 50

  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {Array.from({ length: 5 }).map((_, i) => (
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
        {hasHighPending && (
          <div className="mt-2 flex items-center gap-2 rounded-lg bg-amber-500/20 px-3 py-2 text-sm text-amber-200">
            <AlertTriangle className="size-4" />
            <span>High pending orders: {totalPending} orders</span>
          </div>
        )}
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <MetricItem label="Pending Limit Orders" value={data.pending_limit_orders.toLocaleString("en-IN")} />
          <MetricItem label="Pending Stop Loss" value={data.pending_stop_loss.toLocaleString("en-IN")} />
          <MetricItem label="Pending Take Profit" value={data.pending_take_profit.toLocaleString("en-IN")} />
          <MetricItem label="Pending Auto Sell" value={data.pending_auto_sell.toLocaleString("en-IN")} />
          <MetricItem
            label="Total Pending Value"
            value={formatCurrency(data.total_pending_value)}
            highlight
            className="sm:col-span-2"
          />
        </div>
      </CardContent>
    </Card>
  )
}

function MetricItem({ label, value, highlight = false, className = "" }: { label: string; value: string; highlight?: boolean; className?: string }) {
  return (
    <div className={`rounded-xl border border-white/10 bg-white/5 p-4 ${highlight ? "ring-2 ring-emerald-500/30" : ""} ${className}`}>
      <div className="text-xs text-white/60">{label}</div>
      <div className="mt-1 text-lg font-semibold text-[#fafafa]">{value}</div>
    </div>
  )
}

