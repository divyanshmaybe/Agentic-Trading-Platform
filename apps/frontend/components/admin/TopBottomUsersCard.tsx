"use client"

import type { ComponentPropsWithoutRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { UserPortfolio } from "@/lib/admin"
import { formatCurrency } from "@/lib/admin"

type TopBottomUsersCardProps = {
  topUsers: UserPortfolio[]
  bottomUsers: UserPortfolio[]
  title?: string
  className?: string
  loading?: boolean
} & ComponentPropsWithoutRef<typeof Card>

export function TopBottomUsersCard({
  topUsers,
  bottomUsers,
  title = "Top & Bottom Users",
  className = "",
  loading = false,
  ...cardProps
}: TopBottomUsersCardProps) {
  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="h-48 animate-pulse rounded-xl bg-white/5" />
            <div className="h-48 animate-pulse rounded-xl bg-white/5" />
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div>
          <h3 className="mb-3 text-sm font-semibold text-white/80">Top Performers</h3>
          {topUsers.length > 0 ? (
            <div className="space-y-2">
              {topUsers.slice(0, 10).map((user) => (
                <UserRow key={user.portfolio_id} user={user} />
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-white/20 bg-black/10 px-4 py-6 text-center text-sm text-white/50">
              No top users found
            </div>
          )}
        </div>
        <div>
          <h3 className="mb-3 text-sm font-semibold text-white/80">Bottom Performers</h3>
          {bottomUsers.length > 0 ? (
            <div className="space-y-2">
              {bottomUsers.slice(0, 10).map((user) => (
                <UserRow key={user.portfolio_id} user={user} />
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-white/20 bg-black/10 px-4 py-6 text-center text-sm text-white/50">
              No bottom users found
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function UserRow({ user }: { user: UserPortfolio }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-black/30 px-4 py-3">
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-medium text-white">{user.portfolio_name}</span>
        <span className="text-xs text-white/60">ROI: {user.roi_percentage.toFixed(2)}%</span>
      </div>
      <div className="text-right">
        <div
          className={`text-sm font-medium ${user.realized_pnl >= 0 ? "text-[#22c55e]" : "text-[#ef4444]"}`}
        >
          {formatCurrency(user.realized_pnl)}
        </div>
        <div className="text-xs text-white/60">{user.total_trades} trades</div>
      </div>
    </div>
  )
}

