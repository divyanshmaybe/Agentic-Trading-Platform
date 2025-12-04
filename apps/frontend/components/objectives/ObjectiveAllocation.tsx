"use client"

import { type ObjectiveResponse, type AllocationResultSummary } from "@/lib/objectiveIntake"
import { cn } from "@/lib/utils"

interface ObjectiveAllocationProps {
  objective: ObjectiveResponse
}

function formatPercentage(value: number | null | undefined): string {
  if (value === null || value === undefined) return "N/A"
  return `${(value * 100).toFixed(2)}%`
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "N/A"
  return value.toFixed(4)
}

export function ObjectiveAllocation({ objective }: ObjectiveAllocationProps) {
  // Try to get allocation from structured_payload first, then from raw
  let allocation: AllocationResultSummary | null = null

  if (objective.structured_payload?.allocation) {
    allocation = objective.structured_payload.allocation
  } else if (objective.raw?.allocation) {
    allocation = objective.raw.allocation
  }

  if (!allocation) {
    return null
  }

  const allocationItems = [
    {
      label: "Expected Return",
      value: formatPercentage(allocation.expected_return),
    },
    {
      label: "Expected Risk",
      value: formatPercentage(allocation.expected_risk),
    },
    {
      label: "Objective Value",
      value: formatNumber(allocation.objective_value),
    },
    {
      label: "Regime",
      value: allocation.regime || "N/A",
    },
    {
      label: "Progress Ratio",
      value: formatPercentage(allocation.progress_ratio),
    },
  ]

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-[#fafafa]">Portfolio Allocation</h3>

      {allocation.message && (
        <div className="rounded-lg border border-white/10 bg-white/8 p-4">
          <div className="text-sm text-white/70">{allocation.message}</div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {allocationItems.map((item) => (
          <div
            key={item.label}
            className={cn(
              "rounded-lg border border-white/10 bg-white/8 p-4",
              "hover:bg-white/10 transition-colors"
            )}
          >
            <div className="text-sm text-white/60 mb-1">{item.label}</div>
            <div className="text-base font-medium text-[#fafafa]">{item.value}</div>
          </div>
        ))}
      </div>

      {allocation.weights && Object.keys(allocation.weights).length > 0 && (
        <div className="rounded-lg border border-white/10 bg-white/8 p-4">
          <div className="text-sm font-medium text-white/80 mb-3">Allocation Weights</div>
          <div className="space-y-2">
            {Object.entries(allocation.weights).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between">
                <span className="text-sm text-white/70">{key}</span>
                <span className="text-sm font-medium text-[#fafafa]">
                  {formatPercentage(value)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

