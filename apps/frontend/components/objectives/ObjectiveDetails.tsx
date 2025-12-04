"use client"

import { type ObjectiveResponse } from "@/lib/objectiveIntake"
import { cn } from "@/lib/utils"

interface ObjectiveDetailsProps {
  objective: ObjectiveResponse
}

function formatCurrency(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "N/A"
  const num = typeof value === "string" ? parseFloat(value) : value
  if (isNaN(num)) return "N/A"
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(num)
}

function formatPercentage(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "N/A"
  const num = typeof value === "string" ? parseFloat(value) : value
  if (isNaN(num)) return "N/A"
  return `${num.toFixed(2)}%`
}

function formatNumber(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "N/A"
  const num = typeof value === "string" ? parseFloat(value) : value
  if (isNaN(num)) return "N/A"
  return num.toString()
}

export function ObjectiveDetails({ objective }: ObjectiveDetailsProps) {
  const details = [
    {
      label: "Investable Amount",
      value: formatCurrency(objective.investable_amount),
    },
    {
      label: "Investment Horizon",
      value: objective.investment_horizon_years
        ? `${objective.investment_horizon_years} year${objective.investment_horizon_years !== 1 ? "s" : ""}${objective.investment_horizon_label ? ` (${objective.investment_horizon_label})` : ""}`
        : objective.investment_horizon_label || "N/A",
    },
    {
      label: "Target Return",
      value: formatPercentage(objective.target_return),
    },
    {
      label: "Risk Tolerance",
      value: objective.risk_tolerance
        ? objective.risk_tolerance.charAt(0).toUpperCase() + objective.risk_tolerance.slice(1)
        : "N/A",
    },
    {
      label: "Risk Aversion Lambda",
      value: formatNumber(objective.risk_aversion_lambda),
    },
    {
      label: "Liquidity Needs",
      value: objective.liquidity_needs || "N/A",
    },
    {
      label: "Rebalancing Frequency",
      value: objective.rebalancing_frequency || "N/A",
    },
  ]

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-[#fafafa]">Objective Details</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {details.map((detail) => (
          <div
            key={detail.label}
            className={cn(
              "rounded-lg border border-white/10 bg-white/8 p-4",
              "hover:bg-white/10 transition-colors"
            )}
          >
            <div className="text-sm text-white/60 mb-1">{detail.label}</div>
            <div className="text-base font-medium text-[#fafafa]">{detail.value}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

