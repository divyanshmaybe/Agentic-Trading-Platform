"use client"

import { type ObjectiveResponse } from "@/lib/objectiveIntake"
import { ObjectiveDetails } from "./ObjectiveDetails"
import { ObjectiveConstraints } from "./ObjectiveConstraints"
import { ObjectiveAllocation } from "./ObjectiveAllocation"
import { cn } from "@/lib/utils"

interface ObjectiveDashboardProps {
  objective: ObjectiveResponse
}

function formatDate(dateString: string): string {
  try {
    const date = new Date(dateString)
    return new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date)
  } catch {
    return dateString
  }
}

export function ObjectiveDashboard({ objective }: ObjectiveDashboardProps) {
  const statusColors = {
    active: "bg-green-500/20 text-green-400 border-green-500/30",
    draft: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    inactive: "bg-gray-500/20 text-gray-400 border-gray-500/30",
    complete: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  }

  const completionColors = {
    complete: "bg-green-500/20 text-green-400 border-green-500/30",
    pending: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  }

  const statusColor =
    statusColors[objective.status as keyof typeof statusColors] ||
    statusColors.inactive
  const completionColor =
    completionColors[objective.completion_status as keyof typeof completionColors] ||
    completionColors.pending

  return (
    <div className="space-y-6">
      {/* Header Section */}
      <div className="rounded-lg border border-white/10 bg-white/6 backdrop-blur p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold text-[#fafafa] mb-2">
              {objective.name || "Investment Objective"}
            </h2>
            <div className="flex items-center gap-3 flex-wrap">
              <span
                className={cn(
                  "px-3 py-1 rounded-md text-xs font-medium border",
                  statusColor
                )}
              >
                {objective.status.charAt(0).toUpperCase() + objective.status.slice(1)}
              </span>
              <span
                className={cn(
                  "px-3 py-1 rounded-md text-xs font-medium border",
                  completionColor
                )}
              >
                {objective.completion_status.charAt(0).toUpperCase() +
                  objective.completion_status.slice(1)}
              </span>
              {objective.source && (
                <span className="text-sm text-white/60">Source: {objective.source}</span>
              )}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm text-white/60">
          <div>
            <span className="font-medium text-white/80">Created:</span>{" "}
            {formatDate(objective.created_at)}
          </div>
          <div>
            <span className="font-medium text-white/80">Last Updated:</span>{" "}
            {formatDate(objective.updated_at)}
          </div>
        </div>
      </div>

      {/* Objective Details */}
      <ObjectiveDetails objective={objective} />

      {/* Portfolio Allocation */}
      <ObjectiveAllocation objective={objective} />

      {/* Constraints & Preferences */}
      <ObjectiveConstraints objective={objective} />
    </div>
  )
}
