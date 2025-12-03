"use client"

import { useState, useMemo } from "react"
import type { ComponentPropsWithoutRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react"
import type { AgentSummary } from "@/lib/admin"
import { formatCurrency } from "@/lib/admin"

type AgentLeaderboardCardProps = {
  topAgents: AgentSummary[]
  bottomAgents: AgentSummary[]
  title?: string
  className?: string
  loading?: boolean
} & ComponentPropsWithoutRef<typeof Card>

type SortField = "realized_pnl" | "trade_count" | "win_rate" | "agent_name"
type SortDirection = "asc" | "desc"

export function AgentLeaderboardCard({
  topAgents,
  bottomAgents,
  title = "Agent Leaderboard",
  className = "",
  loading = false,
  ...cardProps
}: AgentLeaderboardCardProps) {
  const [topSortField, setTopSortField] = useState<SortField>("realized_pnl")
  const [topSortDirection, setTopSortDirection] = useState<SortDirection>("desc")
  const [bottomSortField, setBottomSortField] = useState<SortField>("realized_pnl")
  const [bottomSortDirection, setBottomSortDirection] = useState<SortDirection>("asc")

  const sortedTopAgents = useMemo(() => {
    return sortAgents([...topAgents], topSortField, topSortDirection)
  }, [topAgents, topSortField, topSortDirection])

  const sortedBottomAgents = useMemo(() => {
    return sortAgents([...bottomAgents], bottomSortField, bottomSortDirection)
  }, [bottomAgents, bottomSortField, bottomSortDirection])

  const handleSort = (field: SortField, section: "top" | "bottom") => {
    if (section === "top") {
      if (topSortField === field) {
        setTopSortDirection(topSortDirection === "asc" ? "desc" : "asc")
      } else {
        setTopSortField(field)
        setTopSortDirection("desc")
      }
    } else {
      if (bottomSortField === field) {
        setBottomSortDirection(bottomSortDirection === "asc" ? "desc" : "asc")
      } else {
        setBottomSortField(field)
        setBottomSortDirection("asc")
      }
    }
  }

  if (loading) {
    return (
      <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur ${className}`} {...cardProps}>
        <CardHeader>
          <CardTitle className="h-title text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="h-64 animate-pulse rounded-xl bg-white/5" />
            <div className="h-64 animate-pulse rounded-xl bg-white/5" />
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
          <AgentTable
            agents={sortedTopAgents}
            sortField={topSortField}
            sortDirection={topSortDirection}
            onSort={(field) => handleSort(field, "top")}
          />
        </div>
        <div>
          <h3 className="mb-3 text-sm font-semibold text-white/80">Bottom Performers</h3>
          <AgentTable
            agents={sortedBottomAgents}
            sortField={bottomSortField}
            sortDirection={bottomSortDirection}
            onSort={(field) => handleSort(field, "bottom")}
          />
        </div>
      </CardContent>
    </Card>
  )
}

function sortAgents(agents: AgentSummary[], field: SortField, direction: SortDirection): AgentSummary[] {
  return [...agents].sort((a, b) => {
    let comparison = 0
    switch (field) {
      case "realized_pnl":
        comparison = a.realized_pnl - b.realized_pnl
        break
      case "trade_count":
        comparison = a.trade_count - b.trade_count
        break
      case "win_rate":
        comparison = a.win_rate - b.win_rate
        break
      case "agent_name":
        comparison = a.agent_name.localeCompare(b.agent_name)
        break
    }
    return direction === "asc" ? comparison : -comparison
  })
}

function AgentTable({
  agents,
  sortField,
  sortDirection,
  onSort,
}: {
  agents: AgentSummary[]
  sortField: SortField
  sortDirection: SortDirection
  onSort: (field: SortField) => void
}) {
  if (agents.length === 0) {
    return <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-center text-white/60">No agents found</div>
  }

  const typeMap: Record<string, string> = {
    nse_signal: "NSE Signal",
    low_risk: "Low Risk",
    high_risk: "High Risk",
    alpha: "Alpha Copilot",
    liquid: "Liquidity",
  }

  const SortButton = ({ field, label }: { field: SortField; label: string }) => {
    const isActive = sortField === field
    return (
      <button
        onClick={() => onSort(field)}
        className="flex items-center gap-1 hover:text-white"
        type="button"
      >
        {label}
        {isActive ? (
          sortDirection === "asc" ? (
            <ArrowUp className="size-3" />
          ) : (
            <ArrowDown className="size-3" />
          )
        ) : (
          <ArrowUpDown className="size-3 opacity-50" />
        )}
      </button>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-white/10 bg-white/5">
      <table className="w-full">
        <thead>
          <tr className="border-b border-white/10">
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">
              <SortButton field="agent_name" label="Agent Name" />
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">
              <SortButton field="realized_pnl" label="P&L" />
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">
              <SortButton field="trade_count" label="Trades" />
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">
              <SortButton field="win_rate" label="Win Rate" />
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">Type</th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-white/60">Status</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((agent) => (
            <tr key={agent.agent_id} className="border-b border-white/5 hover:bg-white/5">
              <td className="px-4 py-3 text-sm text-white">{agent.agent_name}</td>
              <td
                className={`px-4 py-3 text-sm font-medium ${
                  agent.realized_pnl >= 0 ? "text-[#22c55e]" : "text-[#ef4444]"
                }`}
              >
                {formatCurrency(agent.realized_pnl)}
              </td>
              <td className="px-4 py-3 text-sm text-white/80">{agent.trade_count.toLocaleString("en-IN")}</td>
              <td className="px-4 py-3 text-sm text-white/80">{agent.win_rate.toFixed(2)}%</td>
              <td className="px-4 py-3 text-sm text-white/80">{typeMap[agent.agent_type] || agent.agent_type}</td>
              <td className="px-4 py-3">
                <span
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                    agent.status === "active"
                      ? "bg-emerald-500/20 text-emerald-300"
                      : agent.status === "error"
                        ? "bg-amber-500/20 text-amber-200"
                        : "bg-slate-500/20 text-slate-200"
                  }`}
                >
                  {agent.status.charAt(0).toUpperCase() + agent.status.slice(1)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

