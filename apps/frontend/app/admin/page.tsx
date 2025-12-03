"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import type { ChartData, ScriptableContext } from "chart.js"

import { CompanySettingsCard } from "@/components/admin/CompanySettingsCard"
import { CreateUserModal } from "@/components/admin/CreateUserModal"
import { FinancialStatsCard } from "@/components/admin/FinancialStatsCard"
import { PerformanceCard } from "@/components/admin/PerformanceCard"
import { UserManagementCard } from "@/components/admin/UserManagementCard"
import { MonthlyPnlChart } from "@/components/admin/MonthlyPnlChart"
import { DailyPnlChart } from "@/components/admin/DailyPnlChart"
import { TradesByStatusChart } from "@/components/admin/TradesByStatusChart"
import { TradesBySideChart } from "@/components/admin/TradesBySideChart"
import { HourlyTradeHeatmap } from "@/components/admin/HourlyTradeHeatmap"
import { TradeVolumeChart } from "@/components/admin/TradeVolumeChart"
import { AgentMetricsChart } from "@/components/admin/AgentMetricsChart"
import { AgentPnlSeriesChart } from "@/components/admin/AgentPnlSeriesChart"
import { UserPnlDistributionChart } from "@/components/admin/UserPnlDistributionChart"
import { SymbolConcentrationChart } from "@/components/admin/SymbolConcentrationChart"
import { PortfolioValueChart } from "@/components/admin/PortfolioValueChart"
import { OrganizationSummaryCard } from "@/components/admin/OrganizationSummaryCard"
import { TradingMetricsCard } from "@/components/admin/TradingMetricsCard"
import { PositionMetricsCard } from "@/components/admin/PositionMetricsCard"
import { PendingOrdersCard } from "@/components/admin/PendingOrdersCard"
import { PipelineMetricsCard } from "@/components/admin/PipelineMetricsCard"
import { ExecutionMetricsCard } from "@/components/admin/ExecutionMetricsCard"
import { AlphaMetricsCard } from "@/components/admin/AlphaMetricsCard"
import { AgentLeaderboardCard } from "@/components/admin/AgentLeaderboardCard"
import { UserPortfolioTableCard } from "@/components/admin/UserPortfolioTableCard"
import { TopBottomUsersCard } from "@/components/admin/TopBottomUsersCard"
import type { AdminSettingsForm, AdminSettingsUserField, CreateUserFormValues, DirectoryUser } from "@/components/admin/types"
import { Container } from "@/components/shared/Container"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { createUser, getUsers, type AuthUserSummary, type UserRole, updateUser } from "@/lib/auth"
import { useAuth } from "@/hooks/useAuth"
import { useAdminDashboard } from "@/hooks/useAdminDashboard"
import "@/lib/chart"
import { lineDepthPlugin } from "@/components/dashboard/chartConfig"
import { formatCurrency, computeRoiPct } from "@/lib/admin"
import { AlertTriangle } from "lucide-react"

const POSITIVE_LINE_STYLE = {
  border: "#22c55e",
  gradientFrom: "rgba(34,197,94,0.2)",
  gradientTo: "rgba(34,197,94,0)",
  shadow: "rgba(34,197,94,0.25)",
} as const

const NEGATIVE_LINE_STYLE = {
  border: "#ef4444",
  gradientFrom: "rgba(239,68,68,0.2)",
  gradientTo: "rgba(239,68,68,0)",
  shadow: "rgba(239,68,68,0.25)",
} as const

type LinePalette = typeof POSITIVE_LINE_STYLE | typeof NEGATIVE_LINE_STYLE
type LineDatasetWithShadow = ChartData<"line">["datasets"][number] & { shadowColor: string }

const pickPalette = (series: number[]): LinePalette => {
  if (!series.length) {
    return POSITIVE_LINE_STYLE
  }
  const delta = series[series.length - 1] - series[0]
  return delta >= 0 ? POSITIVE_LINE_STYLE : NEGATIVE_LINE_STYLE
}

const gradientFill = (from: string, to: string) =>
  (context: ScriptableContext<"line">) => {
    const { ctx, chartArea } = context.chart
    if (!chartArea) {
      return from
    }

    const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top)
    gradient.addColorStop(0, from)
    gradient.addColorStop(1, to)
    return gradient
  }

export default function AdminDashboardPage() {
  // Get admin user data securely from server-validated token
  const { user: authUser, loading: authLoading } = useAuth()
  
  // Admin dashboard data with polling
  const {
    dashboard,
    summary,
    loadingDashboard,
    loadingSummary,
    errorDashboard,
    errorSummary,
    lastUpdated,
  } = useAdminDashboard()

  const {
    register: registerSettings,
    handleSubmit: handleSettingsSubmit,
    reset: resetSettingsForm,
  } = useForm<AdminSettingsForm>({
    defaultValues: {
      users: [],
    },
  })

  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [settingsSuccess, setSettingsSuccess] = useState<string | null>(null)

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

  const [teamUsers, setTeamUsers] = useState<AuthUserSummary[]>([])
  const [customerUsers, setCustomerUsers] = useState<AuthUserSummary[]>([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [usersError, setUsersError] = useState<string | null>(null)
  const [selectedRoles, setSelectedRoles] = useState<UserRole[]>(["admin", "staff", "viewer"])
  const [isCreateUserModalOpen, setCreateUserModalOpen] = useState(false)

  // Financial metrics from API
  const financialMetricsData = dashboard?.financial_metrics
  const organizationSummary = dashboard?.organization_summary
  const monthlyPnlSeries = dashboard?.monthly_pnl_series || []
  const portfolioValueSeries = dashboard?.portfolio_value_series || []
  
  // Calculate totals from API data
  const totalInvestment = organizationSummary?.total_invested || 0
  const totalProfit = financialMetricsData?.total_pnl || 0
  const roiPct = financialMetricsData?.overall_roi_percentage || 0

  const formatUserName = useCallback((user: AuthUserSummary) => {
    const fullName = `${user.first_name} ${user.last_name}`.trim()
    return fullName || user.email
  }, [])

  const teamDirectory = useMemo<DirectoryUser[]>(
    () =>
      teamUsers.map((user) => ({
        id: user.id,
        name: formatUserName(user),
        email: user.email,
        role: user.role,
        status: user.status,
        lastActive: formatLastActive(user.last_login_at),
      })),
    [teamUsers, formatUserName],
  )

  const customerDirectory = useMemo<DirectoryUser[]>(
    () =>
      customerUsers.map((user) => ({
        id: user.id,
        name: formatUserName(user),
        email: user.email,
        role: user.role,
        status: user.status,
        lastActive: formatLastActive(user.last_login_at),
      })),
    [customerUsers, formatUserName],
  )

  const combinedDirectory = useMemo(() => {
    const merged = [...teamDirectory, ...customerDirectory]
    return merged.sort((a, b) => a.name.localeCompare(b.name))
  }, [teamDirectory, customerDirectory])

  const filteredDirectory = useMemo(
    () => combinedDirectory.filter((user) => selectedRoles.includes(user.role as UserRole)),
    [combinedDirectory, selectedRoles],
  )

  const teamById = useMemo(() => {
    const map = new Map<string, AuthUserSummary>()
    teamUsers.forEach((user) => {
      map.set(user.id, user)
    })
    return map
  }, [teamUsers])

  const settingsUsers = useMemo<AdminSettingsUserField[]>(
    () =>
      teamUsers.map((user, idx) => ({
        id: user.id,
        name: formatUserName(user),
        email: user.email,
        roleField: `users.${idx}.role` as const,
        activeField: `users.${idx}.active` as const,
      })),
    [teamUsers, formatUserName],
  )

  useEffect(() => {
    resetSettingsForm({
      users: teamUsers.map((user) => ({
        id: user.id,
        role: user.role,
        active: user.status === "active",
      })),
    })
  }, [teamUsers, resetSettingsForm])

  const fetchUsers = useCallback(async () => {
    setUsersLoading(true)
    setUsersError(null)

    try {
      const [staffResponse, customerResponse, adminResponse] = await Promise.all([
        getUsers({ role: "staff", limit: 50 }),
        getUsers({ role: "viewer", limit: 50 }),
        getUsers({ role: "admin", limit: 50 }),
      ])

      const combinedTeam = [...adminResponse.data.users, ...staffResponse.data.users]
      const uniqueTeamById = new Map<string, AuthUserSummary>()
      combinedTeam.forEach((user) => {
        uniqueTeamById.set(user.id, user)
      })

      const sortedTeam = Array.from(uniqueTeamById.values()).sort((a, b) => {
        const nameA = `${a.first_name} ${a.last_name}`.trim().toLowerCase()
        const nameB = `${b.first_name} ${b.last_name}`.trim().toLowerCase()
        return nameA.localeCompare(nameB)
      })

      setTeamUsers(sortedTeam)
      setCustomerUsers(customerResponse.data.users)
    } catch (error) {
      setUsersError(error instanceof Error ? error.message : "Unable to load users")
      setTeamUsers([])
      setCustomerUsers([])
    } finally {
      setUsersLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchUsers()
  }, [fetchUsers])

  useEffect(() => {
    if (!settingsError && !settingsSuccess) {
      return
    }

    const timer = window.setTimeout(() => {
      setSettingsError(null)
      setSettingsSuccess(null)
    }, 5000)

    return () => window.clearTimeout(timer)
  }, [settingsError, settingsSuccess])

  useEffect(() => {
    if (!createUserError && !createUserSuccess) {
      return
    }

    const timer = window.setTimeout(() => {
      setCreateUserError(null)
      setCreateUserSuccess(null)
    }, 5000)

    return () => window.clearTimeout(timer)
  }, [createUserError, createUserSuccess])

  const financialMetrics = useMemo(
    () => [
      {
        label: "Total Investment",
        value: formatCurrency(totalInvestment),
        title: "Total invested capital to date",
      },
      {
        label: "Total P&L",
        value: formatCurrency(totalProfit),
        title: "Profit/Loss accumulated across all strategies",
      },
      {
        label: "ROI",
        value: `${roiPct.toFixed(1)}%`,
        valueClassName: roiPct >= 0 ? "text-[#22c55e]" : "text-[#ef4444]",
        title: "Return on investment for the period",
      },
    ],
    [roiPct, totalInvestment, totalProfit],
  )

  // Chart data from monthly PnL series
  const chart = useMemo(() => {
    if (!monthlyPnlSeries || monthlyPnlSeries.length === 0) {
      return null
    }

    const labels = monthlyPnlSeries.map((d) => d.month)
    const cumulativePnl = monthlyPnlSeries.map((d) => d.cumulative_pnl / 1_000_000) // Convert to millions for display
    
    const companyPalette = pickPalette(cumulativePnl)
    const datasets: ChartData<"line">["datasets"] = [
      {
        label: "Cumulative P&L",
        data: cumulativePnl,
        borderColor: companyPalette.border,
        backgroundColor: gradientFill(companyPalette.gradientFrom, companyPalette.gradientTo),
        borderWidth: 2,
        tension: 0.35,
        fill: true,
        pointRadius: 0,
        borderCapStyle: "round",
        borderJoinStyle: "round",
        shadowColor: companyPalette.shadow,
      } as LineDatasetWithShadow,
    ]

    return {
      data: {
        labels,
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
            callbacks: {
              label: (context: any) => {
                const index = context.dataIndex
                const monthly = monthlyPnlSeries[index].realized_pnl
                const cumulative = monthlyPnlSeries[index].cumulative_pnl
                return [
                  `Monthly: ${formatCurrency(monthly)}`,
                  `Cumulative: ${formatCurrency(cumulative)}`,
                ]
              },
            },
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
            ticks: {
              color: "#9CA3AF",
              callback: (value: any) => `₹${((value as number) * 1_000_000).toLocaleString("en-IN")}`,
            },
          },
        },
      },
      plugins: [lineDepthPlugin],
    }
  }, [monthlyPnlSeries])

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

  const handleSettingsSave = useCallback(
    async (values: AdminSettingsForm) => {
      setSaving(true)
      setSettingsError(null)
      setSettingsSuccess(null)

      try {
        const pendingUpdates = values.users
          .map((formUser) => {
            const original = teamById.get(formUser.id)
            if (!original) return null

            const updates: { role?: "admin" | "staff" | "viewer"; status?: "active" | "inactive" } = {}

            if (formUser.role !== original.role) {
              updates.role = formUser.role
            }

            const originalActive = original.status === "active"
            if (formUser.active !== originalActive) {
              updates.status = formUser.active ? "active" : "inactive"
            }

            if (!Object.keys(updates).length) {
              return null
            }

            return updateUser(formUser.id, updates)
          })
          .filter((update): update is ReturnType<typeof updateUser> => Boolean(update))

        if (!pendingUpdates.length) {
          setSettingsSuccess("No changes to save.")
          setSavedAt(Date.now())
          return
        }

        await Promise.all(pendingUpdates)
        setSettingsSuccess("User permissions updated.")
        setSavedAt(Date.now())
        await fetchUsers()
      } catch (error) {
        setSettingsError(error instanceof Error ? error.message : "Unable to update users")
      } finally {
        setSaving(false)
      }
    },
    [fetchUsers, teamById],
  )

  const handleCreateUserModalOpenChange = useCallback(
    (open: boolean) => {
      setCreateUserModalOpen(open)
      if (!open) {
        setCreateUserError(null)
        setCreateUserSuccess(null)
        resetCreateUserForm({ email: "", password: "", firstName: "", lastName: "", role: "staff" })
      }
    },
    [resetCreateUserForm],
  )

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
        await fetchUsers()
        window.setTimeout(() => {
          handleCreateUserModalOpenChange(false)
        }, 1000)
      } catch (error) {
        setCreateUserError(error instanceof Error ? error.message : "Unable to create user")
      } finally {
        setCreatingUser(false)
      }
    },
    [fetchUsers, handleCreateUserModalOpenChange],
  )

  const handleRoleFilterChange = useCallback((roles: UserRole[]) => {
    setSelectedRoles(roles)
  }, [])

  const handleOpenCreateUserModal = useCallback(() => {
    setCreateUserError(null)
    setCreateUserSuccess(null)
    setCreateUserModalOpen(true)
  }, [])

  const directoryDescription = usersError
    ? usersError
    : usersLoading
      ? "Loading users..."
      : "View all staff and customers. Use the role filter to focus the directory."

  // Show loading state while auth is being verified
  if (authLoading || !authUser) {
    return (
      <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa] flex items-center justify-center">
        <div className="text-white/60">Loading...</div>
      </div>
    )
  }

  // Alert badges
  const hasAlerts = summary && (
    summary.agents_with_errors > 0 ||
    summary.portfolios_in_loss > 0 ||
    (summary.high_concentration_symbols && summary.high_concentration_symbols.length > 0)
  )

  return (
    <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
      <DashboardHeader
        userName={authUser.firstName}
        username={authUser.username}
        userRole={authUser.role}
        onLogout={handleLogout}
      />
      <main className="py-8">
        <Container className="max-w-none space-y-6 px-4 sm:px-6 lg:px-12 xl:px-16">
          {/* Error Banner */}
          {(errorDashboard || errorSummary) && (
            <div className="rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-3 text-red-200">
              {errorDashboard && <div>Dashboard Error: {errorDashboard}</div>}
              {errorSummary && <div>Summary Error: {errorSummary}</div>}
            </div>
          )}

          {/* Alerts Banner */}
          {hasAlerts && summary && (
            <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3">
              {summary.agents_with_errors > 0 && (
                <div className="flex items-center gap-2 text-amber-200">
                  <AlertTriangle className="size-4" />
                  <span>{summary.agents_with_errors} agent(s) with errors</span>
                </div>
              )}
              {summary.portfolios_in_loss > 0 && (
                <div className="flex items-center gap-2 text-amber-200">
                  <AlertTriangle className="size-4" />
                  <span>{summary.portfolios_in_loss} portfolio(s) in loss</span>
                </div>
              )}
              {summary.high_concentration_symbols && summary.high_concentration_symbols.length > 0 && (
                <div className="flex items-center gap-2 text-amber-200">
                  <AlertTriangle className="size-4" />
                  <span>High concentration risk: {summary.high_concentration_symbols.join(", ")}</span>
                </div>
              )}
            </div>
          )}

          <div className="space-y-6">
            {/* Top Row: Summary Cards */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              <OrganizationSummaryCard data={organizationSummary || null} loading={loadingDashboard} className="lg:col-span-1" />
              <FinancialStatsCard metrics={financialMetrics} savedAt={lastUpdated} className="lg:col-span-1" />
              <TradingMetricsCard data={dashboard?.trading_metrics || null} loading={loadingDashboard} className="lg:col-span-1" />
            </div>

            {/* Performance Charts Row */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              {chart ? (
                <PerformanceCard chart={chart} className="lg:col-span-3" />
              ) : (
                <div className="lg:col-span-3 flex h-[360px] items-center justify-center rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur">
                  {loadingDashboard ? "Loading performance data..." : "No performance data available"}
                </div>
              )}
            </div>

            {/* PnL Charts Row */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <MonthlyPnlChart data={monthlyPnlSeries} loading={loadingDashboard} />
              <DailyPnlChart data={dashboard?.daily_pnl_series || []} loading={loadingDashboard} />
            </div>

            {/* Trading Charts Row */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-4">
              <TradesByStatusChart data={dashboard?.trades_by_status || undefined} loading={loadingDashboard} />
              <TradesBySideChart data={dashboard?.trades_by_side || undefined} loading={loadingDashboard} />
              <HourlyTradeHeatmap data={dashboard?.hourly_trade_distribution || []} loading={loadingDashboard} />
              <TradeVolumeChart data={dashboard?.trade_volume_series || []} loading={loadingDashboard} />
            </div>

            {/* Portfolio Value Chart */}
            <PortfolioValueChart data={portfolioValueSeries} loading={loadingDashboard} />

            {/* Agent Metrics Row */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <AgentMetricsChart data={dashboard?.agent_metrics_by_type || []} loading={loadingDashboard} />
              <AgentPnlSeriesChart data={dashboard?.agent_pnl_series || []} loading={loadingDashboard} />
            </div>

            {/* Agent Leaderboard */}
            <AgentLeaderboardCard
              topAgents={dashboard?.top_agents || []}
              bottomAgents={dashboard?.bottom_agents || []}
              loading={loadingDashboard}
            />

            {/* User Portfolio Table */}
            <UserPortfolioTableCard data={dashboard?.user_portfolio_metrics || []} loading={loadingDashboard} />

            {/* User Charts Row */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <UserPnlDistributionChart data={dashboard?.user_pnl_distribution || []} loading={loadingDashboard} />
              <TopBottomUsersCard
                topUsers={dashboard?.top_bottom_users?.top_users || []}
                bottomUsers={dashboard?.top_bottom_users?.bottom_users || []}
                loading={loadingDashboard}
              />
            </div>

            {/* Metrics Cards Row */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-5">
              <PositionMetricsCard data={dashboard?.position_metrics || null} loading={loadingDashboard} />
              <PendingOrdersCard data={dashboard?.pending_orders || null} loading={loadingDashboard} />
              <PipelineMetricsCard data={dashboard?.pipeline_metrics || null} loading={loadingDashboard} />
              <ExecutionMetricsCard data={dashboard?.execution_metrics || null} loading={loadingDashboard} />
              <AlphaMetricsCard data={dashboard?.alpha_metrics || null} loading={loadingDashboard} />
            </div>

            {/* Risk Analysis */}
            <SymbolConcentrationChart data={dashboard?.symbol_concentration || []} loading={loadingDashboard} />

            {/* User Management Section */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <CompanySettingsCard
                users={settingsUsers}
                register={registerSettings}
                onSubmit={handleSettingsSubmit(handleSettingsSave)}
                saving={saving}
                errorMessage={settingsError}
                successMessage={settingsSuccess}
                className="lg:col-span-1"
              />
              <UserManagementCard
                description={directoryDescription}
                users={filteredDirectory}
                selectedRoles={selectedRoles}
                onSelectedRolesChange={handleRoleFilterChange}
                onOpenCreateUser={handleOpenCreateUserModal}
                className="lg:col-span-1"
              />
            </div>
          </div>
        </Container>
        <CreateUserModal
          open={isCreateUserModalOpen}
          onOpenChange={handleCreateUserModalOpenChange}
          register={registerCreateUser}
          errors={createUserErrors}
          onSubmit={handleCreateUserSubmit(handleCreateUser)}
          isSubmitting={creatingUser}
          errorMessage={createUserError}
          successMessage={createUserSuccess}
        />
      </main>
    </div>
  )
}

function formatLastActive(timestamp: string | null) {
  if (!timestamp) return "Never"
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) {
    return "Never"
  }

  return parsed.toLocaleString()
}