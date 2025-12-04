"use client"

import { type ObjectiveResponse } from "@/lib/objectiveIntake"
import { cn } from "@/lib/utils"

interface ObjectiveConstraintsProps {
  objective: ObjectiveResponse
}

function formatFieldName(key: string): string {
  return key
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ")
}

function formatFieldValue(value: any): string {
  if (value === null || value === undefined) {
    return "Not set"
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No"
  }
  if (typeof value === "object") {
    if (Array.isArray(value)) {
      if (value.length === 0) {
        return "None"
      }
      return value.join(", ")
    }
    if (Object.keys(value).length === 0) {
      return "None"
    }
    return JSON.stringify(value, null, 2)
  }
  return String(value)
}

function renderFieldCards(data: Record<string, any>, title: string) {
  if (!data || Object.keys(data).length === 0) {
    return null
  }

  return (
    <div className="space-y-3">
      <div className="text-sm font-medium text-white/80">{title}</div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {Object.entries(data).map(([key, value]) => (
          <div
            key={key}
            className={cn(
              "rounded-lg border border-white/10 bg-white/8 p-3",
              "hover:bg-white/10 transition-colors"
            )}
          >
            <div className="text-xs text-white/60 mb-1">{formatFieldName(key)}</div>
            <div className="text-sm font-medium text-[#fafafa] wrap-break-word">
              {formatFieldValue(value)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function hasConstraintsData(objective: ObjectiveResponse): boolean {
  return !!(
    (objective.constraints && Object.keys(objective.constraints).length > 0) ||
    (objective.preferences && Object.keys(objective.preferences).length > 0) ||
    (objective.generic_notes && objective.generic_notes.length > 0)
  )
}

export function ObjectiveConstraints({ objective }: ObjectiveConstraintsProps) {
  if (!hasConstraintsData(objective)) {
    return null
  }

  return (
    <div className="space-y-6">
      <h3 className="text-lg font-semibold text-[#fafafa]">Constraints & Preferences</h3>

      {objective.constraints && Object.keys(objective.constraints).length > 0 && (
        <div className="rounded-lg border border-white/10 bg-white/8 backdrop-blur p-4">
          {renderFieldCards(objective.constraints, "Constraints")}
        </div>
      )}

      {objective.preferences && Object.keys(objective.preferences).length > 0 && (
        <div className="rounded-lg border border-white/10 bg-white/8 backdrop-blur p-4">
          {renderFieldCards(objective.preferences, "Preferences")}
        </div>
      )}

      {objective.generic_notes && objective.generic_notes.length > 0 && (
        <div className="rounded-lg border border-white/10 bg-white/8 backdrop-blur p-4">
          <div className="text-sm font-medium text-white/80 mb-3">Notes</div>
          <ul className="space-y-2">
            {objective.generic_notes.map((note, index) => (
              <li key={index} className="text-sm text-white/70">
                • {typeof note === "string" ? note : JSON.stringify(note)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

