"use client"

import { useCallback, useMemo, useState } from "react"
import { useForm } from "react-hook-form"

import { CompanySettingsCard } from "@/components/admin/CompanySettingsCard"
import { CreateUserCard } from "@/components/admin/CreateUserCard"
import { FinancialStatsCard } from "@/components/admin/FinancialStatsCard"
import { PerformanceCard } from "@/components/admin/PerformanceCard"
import { UserDirectoryCard } from "@/components/admin/UserDirectoryCard"
import type { AdminSettingsForm, AdminSettingsUserField, CreateUserFormValues } from "@/components/admin/types"
import { Container } from "@/components/shared/Container"
import { AppHeader } from "@/components/layout/AppHeader"
import { CUSTOMER_USERS, STAFF_USERS } from "@/data/adminUsers"
import { createUser } from "@/lib/auth"
import "@/lib/chart"
import {
  type DashboardData,
  computeRoiPct,
  formatCurrency,
  getDashboardData,
  getTopKInvestors,
} from "@/lib/dashboardData"

export default function AdminDashboardPage() {
  const initial: DashboardData = getDashboardData()
  const [data] = useState<DashboardData>(initial)

  const {
    register: registerSettings,
    handleSubmit: handleSettingsSubmit,
  } = useForm<AdminSettingsForm>({
    defaultValues: {
      users: data.investors.map((u) => ({ id: u.id, role: "Viewer", active: true })),
    },
  })

  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  const {
    register: registerCreateUser,
    handleSubmit: handleCreateUserSubmit,
    reset: resetCreateUserForm,
    formState: { errors: createUserErrors },
  } = useForm<CreateUserFormValues>({
    defaultValues: {
      role: "staff",
    },
  })

  const [creatingUser, setCreatingUser] = useState(false)
  const [createUserError, setCreateUserError] = useState<string | null>(null)
  const [createUserSuccess, setCreateUserSuccess] = useState<string | null>(null)

  const months = data.months
  const totals = data.companyTotals
  const totalInvestment = totals[totals.length - 1] * 1_000_000
  const totalProfit = (totals[totals.length - 1] - totals[0]) * 1_000_000
  const roiPct = computeRoiPct(totals)

  const topK = useMemo(() => getTopKInvestors(data.investors, 3), [data.investors])

  const settingsUsers = useMemo<AdminSettingsUserField[]>(
    () =>
      data.investors.slice(0, 6).map((u, idx) => ({
        id: u.id,
        name: u.name,
        value: formatCurrency(u.value),
        roleField: `users.${idx}.role` as const,
        activeField: `users.${idx}.active` as const,
      })),
    [data.investors],
  )

  const financialMetrics = useMemo(
    () => [
      {
        label: "Total Investment",
        value: formatCurrency(totalInvestment),
        title: "Total invested capital to date",
      },
      {
        label: "Total Profit",
        value: formatCurrency(totalProfit),
        title: "Profit accumulated across all strategies",
      },
      {
        label: "ROI",
        value: `${roiPct.toFixed(1)}%`,
        valueClassName: roiPct >= 0 ? "text-[#00FF88]" : "text-rose-400",
        title: "Return on investment for the period",
      },
    ],
    [roiPct, totalInvestment, totalProfit],
  )

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
        animation: { duration: 700, easing: "easeOutQuart" as const },
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

  const handleSettingsSave = (values: AdminSettingsForm) => {
    setSaving(true)
    setTimeout(() => {
      setSaving(false)
      setSavedAt(Date.now())
      // eslint-disable-next-line no-console
      console.log("Saved settings", values)
    }, 700)
  }

  const handleCreateUser = useCallback(
    async (values: CreateUserFormValues) => {
      setCreatingUser(true)
      setCreateUserError(null)
      setCreateUserSuccess(null)

      try {
        const response = await createUser({
          email: values.email.trim(),
          password: values.password,
          first_name: values.firstName.trim(),
          last_name: values.lastName.trim(),
          role: values.role,
        })

        setCreateUserSuccess(`User ${response.data.email} created successfully.`)
        resetCreateUserForm({ email: "", password: "", firstName: "", lastName: "", role: "staff" })
      } catch (error) {
        setCreateUserError(error instanceof Error ? error.message : "Unable to create user")
      } finally {
        setCreatingUser(false)
      }
    },
    [resetCreateUserForm],
  )

  return (
    <>
      <AppHeader subtitle="admin" onLogout={handleLogout} className="bg-black" />
      <main className="py-6">
        <Container className="space-y-6 max-w-7xl">
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-12">
            <PerformanceCard chart={chart} />
            <FinancialStatsCard metrics={financialMetrics} savedAt={savedAt} />
            <CompanySettingsCard
              users={settingsUsers}
              register={registerSettings}
              onSubmit={handleSettingsSubmit(handleSettingsSave)}
              saving={saving}
            />
            <CreateUserCard
              register={registerCreateUser}
              errors={createUserErrors}
              onSubmit={handleCreateUserSubmit(handleCreateUser)}
              isSubmitting={creatingUser}
              errorMessage={createUserError}
              successMessage={createUserSuccess}
            />
            <UserDirectoryCard
              title="Staff"
              description="Core team managing strategies, risk, and client success."
              users={STAFF_USERS}
              className="sm:col-span-1 lg:col-span-4"
            />
            <UserDirectoryCard
              title="Customers"
              description="Active investors onboarded on AlphaPilot portfolios."
              users={CUSTOMER_USERS}
              className="sm:col-span-1 lg:col-span-4"
            />
          </div>
        </Container>
      </main>
    </>
  )
}