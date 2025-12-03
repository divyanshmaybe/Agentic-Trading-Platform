import type { ComponentPropsWithoutRef } from "react"

import { FilterIcon, UsersIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

import type { UserRole } from "@/lib/auth"

import type { DirectoryUser } from "./types"

type UserManagementCardProps = {
  description: string
  users: DirectoryUser[]
  selectedRoles: UserRole[]
  onSelectedRolesChange: (roles: UserRole[]) => void
  onOpenCreateUser: () => void
  emptyMessage?: string
} & ComponentPropsWithoutRef<typeof Card>

const ROLE_OPTIONS: Array<{ label: string; value: UserRole }> = [
  { label: "Admin", value: "admin" },
  { label: "Staff", value: "staff" },
  { label: "Viewer", value: "viewer" },
]

export function UserManagementCard({
  description,
  users,
  selectedRoles,
  onSelectedRolesChange,
  onOpenCreateUser,
  emptyMessage = "No users match the selected roles.",
  className = "",
  ...cardProps
}: UserManagementCardProps) {
  const allSelected = ROLE_OPTIONS.every((option) => selectedRoles.includes(option.value))

  const selectedLabel = allSelected
    ? "All roles"
    : selectedRoles.length
      ? ROLE_OPTIONS.filter((option) => selectedRoles.includes(option.value))
          .map((option) => option.label)
          .join(", ")
      : "No roles"

  const toggleRole = (role: UserRole, checked: boolean) => {
    if (checked) {
      const nextRoles = Array.from(new Set([...selectedRoles, role]))
      onSelectedRolesChange(nextRoles)
      return
    }

    const nextRoles = selectedRoles.filter((value) => value !== role)
    onSelectedRolesChange(nextRoles)
  }

  const handleResetFilters = () => {
    onSelectedRolesChange(ROLE_OPTIONS.map((option) => option.value))
  }

  return (
    <Card
      className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur flex h-full flex-col lg:col-span-12 ${className}`}
      {...cardProps}
    >
      <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <CardTitle className="h-title text-xl">User Management</CardTitle>
          <p className="text-sm text-white/60">{description}</p>
        </div>
        <div className="flex gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                className="border-white/15 bg-white/5 px-4 py-2 text-white hover:bg-white/10"
              >
                <FilterIcon className="mr-2 size-4" aria-hidden />
                <span className="text-sm">{selectedLabel}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-48 border-white/10 bg-black/90 text-white"
            >
              <DropdownMenuLabel className="text-xs uppercase tracking-wide text-white/40">
                Filter by role
              </DropdownMenuLabel>
              <DropdownMenuSeparator className="bg-white/10" />
              {ROLE_OPTIONS.map((option) => (
                <DropdownMenuCheckboxItem
                  key={option.value}
                  checked={selectedRoles.includes(option.value)}
                  className="data-[state=checked]:bg-emerald-500/10 data-[state=checked]:text-emerald-200"
                  onCheckedChange={(checked) => toggleRole(option.value, Boolean(checked))}
                >
                  {option.label}
                </DropdownMenuCheckboxItem>
              ))}
              <DropdownMenuSeparator className="bg-white/10" />
              <DropdownMenuItem onSelect={(event) => { event.preventDefault(); handleResetFilters() }}>
                Select all
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            type="button"
            onClick={onOpenCreateUser}
            className="border border-emerald-400/30 bg-emerald-500/20 px-4 py-2 text-emerald-200 hover:bg-emerald-500/30"
          >
            <UsersIcon className="mr-2 size-4" aria-hidden />
            Create user
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="max-h-96 space-y-3 overflow-y-auto pr-2" role="list">
            {users.length ? (
              users.map((user) => (
                <UserRow key={user.id} user={user} />
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-white/20 bg-black/10 px-4 py-6 text-center text-sm text-white/50">
                {emptyMessage}
              </div>
            )}
          </div>
          <div className="mt-4 flex items-center justify-end gap-2 text-xs text-white/50">
            <span>Showing {users.length} users</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

type UserRowProps = {
  user: DirectoryUser
}

function UserRow({ user }: UserRowProps) {
  return (
    <div
      role="listitem"
      className="flex items-start justify-between gap-3 rounded-xl border border-white/10 bg-black/30 px-4 py-3"
    >
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-medium text-white">{user.name}</span>
        <span className="truncate text-xs text-white/60">{user.email}</span>
        <span className="text-xs text-white/50 capitalize">{user.role}</span>
      </div>
      <div className="text-right text-xs text-white/60">
        <StatusBadge status={user.status} />
        <div className="mt-1">{user.lastActive}</div>
      </div>
    </div>
  )
}

type StatusBadgeProps = {
  status: DirectoryUser["status"]
}

function StatusBadge({ status }: StatusBadgeProps) {
  const statusClasses: Record<DirectoryUser["status"], string> = {
    active: "bg-emerald-500/20 text-emerald-300",
    suspended: "bg-amber-500/20 text-amber-200",
    inactive: "bg-slate-500/20 text-slate-200",
  }

  const badgeClass = statusClasses[status]

  return (
    <span className={`inline-flex items-center justify-center rounded-full px-2 py-0.5 text-[11px] font-medium ${badgeClass}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  )
}

