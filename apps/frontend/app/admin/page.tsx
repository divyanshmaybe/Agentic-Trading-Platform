"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import type { ChartData, ScriptableContext } from "chart.js"

import { CompanySettingsCard } from "@/components/admin/CompanySettingsCard"
import { CreateUserModal } from "@/components/admin/CreateUserModal"
import { FinancialStatsCard } from "@/components/admin/FinancialStatsCard"
import { PerformanceCard } from "@/components/admin/PerformanceCard"
import { UserManagementCard } from "@/components/admin/UserManagementCard"
import type { AdminSettingsForm, AdminSettingsUserField, CreateUserFormValues, DirectoryUser } from "@/components/admin/types"
import { Container } from "@/components/shared/Container"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { createUser, getUsers, type AuthUserSummary, type UserRole, updateUser } from "@/lib/auth"
import { useAuth } from "@/hooks/useAuth"
import "@/lib/chart"
import { lineDepthPlugin } from "@/components/dashboard/chartConfig"
import {
  type DashboardData,
  computeRoiPct,
  formatCurrency,
  getDashboardData,
} from "@/lib/dashboardData"

const POSITIVE_LINE_STYLE = {
  border: "#22c55e",
  gradientFrom: "rgba(34,197,94,0.2)",
  gradientSoft: "rgba(34,197,94,0.12)",
  gradientTo: "rgba(34,197,94,0)",
  shadow: "rgba(34,197,94,0.25)",
} as const

const NEGATIVE_LINE_STYLE = {
  border: "#ef4444",
  gradientFrom: "rgba(239,68,68,0.2)",
  gradientSoft: "rgba(239,68,68,0.12)",
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
  const initial: DashboardData = getDashboardData()
  const [data] = useState<DashboardData>(initial)

  // Get admin user data securely from server-validated token
  const { user: authUser, loading: authLoading } = useAuth()

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

  const months = data.months
  const totals = data.companyTotals
  const totalInvestment = totals[totals.length - 1] * 1_000_000
  const totalProfit = (totals[totals.length - 1] - totals[0]) * 1_000_000
  const roiPct = computeRoiPct(totals)

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
        label: "Total Profit",
        value: formatCurrency(totalProfit),
        title: "Profit accumulated across all strategies",
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

  const chart = useMemo(() => {
    const companyPalette = pickPalette(totals)
    const datasets: ChartData<"line">["datasets"] = [
      {
        label: "Company",
        data: totals,
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
      plugins: [lineDepthPlugin],
    }
  }, [months, totals])

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

  return (
    <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
      <DashboardHeader
        userName={authUser.firstName}
        username={authUser.username}
        userRole={authUser.role}
        onLogout={handleLogout}
      />
      <main className="py-8">
        <Container className="space-y-6">
          <div className="space-y-6">
            <PerformanceCard chart={chart} />
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <FinancialStatsCard metrics={financialMetrics} savedAt={savedAt} className="lg:col-span-1" />
              <CompanySettingsCard
                users={settingsUsers}
                register={registerSettings}
                onSubmit={handleSettingsSubmit(handleSettingsSave)}
                saving={saving}
                errorMessage={settingsError}
                successMessage={settingsSuccess}
                className="lg:col-span-1"
              />
            </div>
            <UserManagementCard
              description={directoryDescription}
              users={filteredDirectory}
              selectedRoles={selectedRoles}
              onSelectedRolesChange={handleRoleFilterChange}
              onOpenCreateUser={handleOpenCreateUserModal}
            />
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