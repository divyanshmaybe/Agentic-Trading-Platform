"use client"

import { useCallback, useMemo, useState } from "react"
import "@/lib/chart"
import { Line } from "react-chartjs-2"
import { Container } from "@/components/shared/Container"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useForm } from "react-hook-form"
import { AppHeader } from "@/components/layout/AppHeader"
import {
  DashboardData,
  Investor,
  computeRoiPct,
  formatCurrency,
  getDashboardData,
  getTopKInvestors,
} from "@/lib/dashboardData"

type SettingsForm = {
  users: { id: string; role: Investor["role"]; active: boolean }[]
}

export default function AdminDashboardPage() {
  const initial: DashboardData = getDashboardData()
  const [data] = useState<DashboardData>(initial)

  const { register, handleSubmit, watch, setValue } = useForm<SettingsForm>({
    defaultValues: {
      users: data.investors.map((u) => ({ id: u.id, role: "Viewer", active: true })),
    },
  })
  const formUsers = watch("users")

  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  const months = data.months
  const totals = data.companyTotals
  const totalInvestment = totals[totals.length - 1] * 1_000_000
  const totalProfit = (totals[totals.length - 1] - totals[0]) * 1_000_000
  const roiPct = computeRoiPct(totals)

  const topK = useMemo(() => getTopKInvestors(data.investors, 3), [data.investors])

  const chart = useMemo(() => {
    const gradientFor = (ctx: CanvasRenderingContext2D) => {
      const g = ctx.createLinearGradient(0, 0, 0, 320)
      g.addColorStop(0, "rgba(0,255,136,0.35)")
      g.addColorStop(1, "rgba(0,255,136,0.02)")
      return g
    }

    const datasets = [
      {
        label: "Company",
        data: totals,
        borderColor: "#00FF88",
        backgroundColor: (ctx: any) => gradientFor(ctx.chart.ctx),
        borderWidth: 2,
        tension: 0.35,
        fill: true,
        pointRadius: 0,
      },
      ...topK.slice(0, 2).map((inv, idx) => ({
        label: inv.name,
        data: inv.series,
        borderColor: idx === 0 ? "#22d3ee" : "#60a5fa",
        backgroundColor: "transparent",
        borderWidth: 1.6,
        pointRadius: 0,
        tension: 0.35,
        fill: false,
      })),
    ]

    const glowPlugin = {
      id: "neon-glow",
      afterDatasetsDraw(chart: any) {
        const { ctx } = chart
        chart.data.datasets.forEach((_: any, i: number) => {
          const meta = chart.getDatasetMeta(i)
          if (!meta.hidden && meta.dataset) {
            ctx.save()
            ctx.shadowColor = "rgba(0,255,136,0.6)"
            ctx.shadowBlur = i === 0 ? 16 : 6
            ctx.lineWidth = i === 0 ? 2 : 1.5
            ctx.strokeStyle = i === 0 ? "#00FF88" : ctx.strokeStyle
            ctx.beginPath()
            meta.dataset.draw(ctx)
            ctx.restore()
          }
        })
      },
    }

    return {
      data: {
        labels: months,
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 700, easing: "easeOutQuart" },
        plugins: {
          legend: {
            labels: {
              color: "#E5E5E5",
              font: { family: "Playfair Display" },
            },
          },
          tooltip: {
            mode: "index" as const,
            intersect: false,
            backgroundColor: "rgba(22,26,30,0.95)",
            borderColor: "#1f2937",
            borderWidth: 1,
            titleColor: "#E5E5E5",
            bodyColor: "#9CA3AF",
          },
        },
        interaction: { mode: "nearest" as const, intersect: false },
        scales: {
          x: {
            grid: { color: "rgba(255,255,255,0.05)" },
            ticks: { color: "#9CA3AF" },
          },
          y: {
            grid: { color: "rgba(255,255,255,0.05)" },
            ticks: { color: "#9CA3AF" },
          },
        },
      },
      plugins: [glowPlugin],
    }
  }, [months, totals, topK])

  const handleLogout = useCallback(() => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("access_token")
      localStorage.removeItem("refresh_token")
      localStorage.removeItem("user_id")
      localStorage.removeItem("organization_id")
    }
    if (typeof window !== "undefined") {
      window.location.href = "/login"
    }
  }, [])

  function handleRoleChange(id: string, role: Investor["role"]) {
    const idx = formUsers.findIndex((u) => u.id === id)
    if (idx >= 0) setValue(`users.${idx}.role`, role, { shouldDirty: true })
  }
  function handleActiveToggle(id: string, active: boolean) {
    const idx = formUsers.findIndex((u) => u.id === id)
    if (idx >= 0) setValue(`users.${idx}.active`, active, { shouldDirty: true })
  }
  function onSubmit(values: SettingsForm) {
    setSaving(true)
    setTimeout(() => {
      setSaving(false)
      setSavedAt(Date.now())
      // eslint-disable-next-line no-console
      console.log("Saved settings", values)
    }, 700)
  }

  return (
    <>
      <AppHeader subtitle="admin" onLogout={handleLogout} className="bg-black" />
      <main className="py-6">
        <Container className="space-y-6">
        {/* Grid */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Stats card */}
          <Card className="card-glass neon-hover rounded-2xl lg:col-span-6">
            <CardHeader>
              <CardTitle className="h-title text-xl`">Key Financial Stats</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Stat label="Total Investment" value={formatCurrency(totalInvestment)} title="Total invested capital to date" />
                <Stat label="Total Profit" value={formatCurrency(totalProfit)} title="Profit accumulated across all strategies" />
                <Stat
                  label="ROI"
                  value={`${roiPct.toFixed(1)}%`}
                  valueClassName={roiPct >= 0 ? "text-[#00FF88]" : "text-rose-400"}
                  title="Return on investment for the period"
                />
              </div>
              <div className="mt-2 text-xs text-white/60">{savedAt ? `Last saved ${new Date(savedAt).toLocaleTimeString()}` : "\u00A0"}</div>
            </CardContent>
          </Card>

          {/* User list */}
          <Card className="card-glass neon-hover rounded-2xl lg:col-span-6">
            <CardHeader>
              <CardTitle className="h-title text-xl">Investors</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="max-h-64 space-y-3 overflow-auto pr-2" role="list">
                {data.investors.map((inv) => (
                  <div
                    key={inv.id}
                    role="listitem"
                    className="neon-hover flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-4 py-3"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="size-8 rounded-full bg-white/10 ring-1 ring-white/30" />
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{inv.name}</div>
                        <div className="text-xs text-white/60">{formatCurrency(inv.value)}</div>
                      </div>
                    </div>
                    <div
                      className={`text-sm font-medium ${
                        inv.growthPct >= 0 ? "text-[#00FF88]" : "text-rose-400"
                      }`}
                    >
                      {inv.growthPct >= 0 ? "+" : ""}
                      {inv.growthPct}%
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Chart */}
          <Card className="card-glass neon-hover rounded-2xl lg:col-span-8">
            <CardHeader>
              <CardTitle className="h-title text-xl">Performance</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-[360px] w-full rounded-xl border border-white/10 bg-black/20 p-2">
                <Line data={chart.data} options={chart.options as any} plugins={chart.plugins as any} />
              </div>
            </CardContent>
          </Card>

          {/* Settings */}
          <form
            onSubmit={handleSubmit(onSubmit)}
            className="card-glass neon-hover rounded-2xl lg:col-span-4"
            role="region"
            aria-label="Company Settings"
          >
            <CardHeader>
              <CardTitle className="h-title text-xl">Company Settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-3">
                {data.investors.slice(0, 6).map((u, idx) => (
                  <div
                    key={u.id}
                    className="neon-hover flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 p-3"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{u.name}</div>
                      <div className="text-xs text-white/60">{formatCurrency(u.value)}</div>
                    </div>
                    <div className="flex items-center gap-3">
                      <select
                        {...register(`users.${idx}.role`)}
                        defaultValue="Viewer"
                        onChange={(e) => handleRoleChange(u.id, e.target.value as Investor["role"])}
                        className="rounded-md border border-white/10 bg-black/40 px-2.5 py-1.5 text-sm text-white focus:outline-none"
                        aria-label={`Role for ${u.name}`}
                      >
                        <option>Viewer</option>
                        <option>Editor</option>
                        <option>Admin</option>
                      </select>
                      <label className="inline-flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          {...register(`users.${idx}.active`)}
                          defaultChecked
                          onChange={(e) => handleActiveToggle(u.id, e.target.checked)}
                          className="size-4 rounded border-white/20 bg-black/40 accent-white"
                          aria-label={`Active state for ${u.name}`}
                        />
                        <span className="text-white/80">Active</span>
                      </label>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-end">
                <Button
                  type="submit"
                  disabled={saving}
                  className="neon-hover border border-white/10 bg-white/10 text-white hover:bg-white/20"
                  aria-busy={saving}
                >
                  {saving ? "Saving..." : "Save changes"}
                </Button>
              </div>
            </CardContent>
          </form>
        </div>
        </Container>
      </main>
    </>
  )
}

function Stat({
  label,
  value,
  valueClassName,
  title,
}: {
  label: string
  value: string
  valueClassName?: string
  title?: string
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4" title={title}>
      <div className="text-xs text-white/60">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${valueClassName ?? ""}`}>{value}</div>
    </div>
  )
}


