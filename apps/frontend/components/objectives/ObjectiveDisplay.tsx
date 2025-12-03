import React from "react"
import { ObjectiveResponse } from "@/lib/objectiveIntake"

interface ObjectiveDisplayProps {
  objective: ObjectiveResponse
}

export function ObjectiveDisplay({ objective }: ObjectiveDisplayProps) {
  const formatCurrency = (amount: number | null | undefined) => {
    if (amount == null) return "N/A"
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount)
  }

  const formatPercentage = (value: number | null | undefined) => {
    if (value == null) return "N/A"
    return `${(value * 100).toFixed(2)}%`
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  const renderValue = (value: any, depth: number = 0): React.ReactNode => {
    if (value === null || value === undefined) {
      return <span className="text-white/50">N/A</span>
    }

    if (Array.isArray(value)) {
      if (value.length === 0) {
        return <span className="text-white/50">Empty</span>
      }
      return (
        <div className="space-y-1">
          {value.map((item, idx) => (
            <div key={idx} className="text-xs bg-black/30 rounded px-2 py-1">
              {renderValue(item, depth + 1)}
            </div>
          ))}
        </div>
      )
    }

    if (typeof value === "object") {
      return (
        <div className={`space-y-1 ${depth > 0 ? "ml-2 border-l border-white/10 pl-2" : ""}`}>
          {Object.entries(value).map(([k, v]) => (
            <div key={k} className="text-xs">
              <span className="text-white/60 capitalize">{k.replace(/_/g, " ")}:</span>{" "}
              <span className="text-white/90">{renderValue(v, depth + 1)}</span>
            </div>
          ))}
        </div>
      )
    }

    // Handle boolean, number, string
    if (typeof value === "boolean") {
      return <span>{value ? "Yes" : "No"}</span>
    }

    if (typeof value === "number") {
      // Format numbers appropriately
      if (value % 1 !== 0) {
        return <span>{value.toFixed(2)}</span>
      }
      return <span>{value.toLocaleString()}</span>
    }

    return <span>{String(value)}</span>
  }

  const renderObjectAsCards = (obj: Record<string, any>, title: string) => {
    return (
      <div className="bg-black/30 rounded-lg p-4 border border-white/10">
        <h3 className="text-sm font-medium text-white/60 mb-3">{title}</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {Object.entries(obj).map(([key, value]) => (
            <div key={key} className="bg-black/40 rounded p-3 border border-white/5">
              <div className="text-xs font-medium text-white/60 mb-2 capitalize">
                {key.replace(/_/g, " ")}
              </div>
              <div className="text-sm text-white/90">{renderValue(value)}</div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const renderArrayAsCards = (arr: any[], title: string) => {
    return (
      <div className="bg-black/30 rounded-lg p-4 border border-white/10">
        <h3 className="text-sm font-medium text-white/60 mb-3">{title}</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {arr.map((item, index) => (
            <div key={index} className="bg-black/40 rounded p-3 border border-white/5">
              <div className="text-sm text-white/90">{renderValue(item)}</div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      <div className="space-y-4">
        {/* Header Section */}
        <div className="border-b border-white/10 pb-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-semibold text-[#fafafa]">
                {objective.name || "Investment Objective"}
              </h2>
              <p className="text-sm text-white/60 mt-1">ID: {objective.id}</p>
            </div>
            <div className="flex items-center gap-2">
              <span
                className={`px-3 py-1 rounded-full text-xs font-medium ${
                  objective.status === "active"
                    ? "bg-green-500/20 text-green-400"
                    : "bg-gray-500/20 text-gray-400"
                }`}
              >
                {objective.status}
              </span>
              <span
                className={`px-3 py-1 rounded-full text-xs font-medium ${
                  objective.completion_status === "complete"
                    ? "bg-blue-500/20 text-blue-400"
                    : "bg-yellow-500/20 text-yellow-400"
                }`}
              >
                {objective.completion_status}
              </span>
            </div>
          </div>
        </div>

        {/* Investment Parameters */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-black/30 rounded-lg p-4 border border-white/10">
            <h3 className="text-sm font-medium text-white/60 mb-2">Investable Amount</h3>
            <p className="text-xl font-semibold text-[#fafafa]">
              {formatCurrency(objective.investable_amount)}
            </p>
          </div>

          <div className="bg-black/30 rounded-lg p-4 border border-white/10">
            <h3 className="text-sm font-medium text-white/60 mb-2">Investment Horizon</h3>
            <p className="text-xl font-semibold text-[#fafafa]">
              {objective.investment_horizon_years
                ? `${objective.investment_horizon_years} years`
                : objective.investment_horizon_label || "N/A"}
            </p>
          </div>

          <div className="bg-black/30 rounded-lg p-4 border border-white/10">
            <h3 className="text-sm font-medium text-white/60 mb-2">Target Return</h3>
            <p className="text-xl font-semibold text-[#fafafa]">
              {formatPercentage(objective.target_return)}
            </p>
          </div>

          <div className="bg-black/30 rounded-lg p-4 border border-white/10">
            <h3 className="text-sm font-medium text-white/60 mb-2">Risk Tolerance</h3>
            <p className="text-xl font-semibold text-[#fafafa] capitalize">
              {objective.risk_tolerance || "N/A"}
            </p>
          </div>

          {objective.liquidity_needs && (
            <div className="bg-black/30 rounded-lg p-4 border border-white/10">
              <h3 className="text-sm font-medium text-white/60 mb-2">Liquidity Needs</h3>
              <p className="text-xl font-semibold text-[#fafafa] capitalize">
                {objective.liquidity_needs}
              </p>
            </div>
          )}

          {objective.rebalancing_frequency && (
            <div className="bg-black/30 rounded-lg p-4 border border-white/10">
              <h3 className="text-sm font-medium text-white/60 mb-2">Rebalancing Frequency</h3>
              <p className="text-xl font-semibold text-[#fafafa] capitalize">
                {objective.rebalancing_frequency}
              </p>
            </div>
          )}
        </div>

        {/* Risk Aversion Lambda */}
        {objective.risk_aversion_lambda != null && (
          <div className="bg-black/30 rounded-lg p-4 border border-white/10">
            <h3 className="text-sm font-medium text-white/60 mb-2">Risk Aversion Lambda</h3>
            <p className="text-lg font-semibold text-[#fafafa]">
              {objective.risk_aversion_lambda.toFixed(4)}
            </p>
          </div>
        )}

        {/* Structured Payload */}
        {objective.structured_payload &&
          Object.keys(objective.structured_payload).length > 0 &&
          renderObjectAsCards(objective.structured_payload, "Structured Payload")}

        {/* Constraints */}
        {objective.constraints &&
          Object.keys(objective.constraints).length > 0 &&
          renderObjectAsCards(objective.constraints, "Constraints")}

        {/* Preferences */}
        {objective.preferences &&
          Object.keys(objective.preferences).length > 0 &&
          renderObjectAsCards(objective.preferences, "Preferences")}

        {/* Generic Notes */}
        {objective.generic_notes && objective.generic_notes.length > 0 && (
          <div className="bg-black/30 rounded-lg p-4 border border-white/10">
            <h3 className="text-sm font-medium text-white/60 mb-3">Notes</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {objective.generic_notes.map((note, index) => (
                <div
                  key={index}
                  className="bg-black/40 rounded p-3 border border-white/5"
                >
                  {typeof note === "string" ? (
                    <p className="text-sm text-white/90">{note}</p>
                  ) : typeof note === "object" && note !== null ? (
                    <div className="space-y-1">
                      {Object.entries(note).map(([key, value]) => (
                        <div key={key} className="text-sm">
                          <span className="text-white/60 capitalize">{key.replace(/_/g, " ")}:</span>{" "}
                          <span className="text-white/90">{String(value)}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-white/90">{String(note)}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Target Returns */}
        {objective.target_returns &&
          objective.target_returns.length > 0 &&
          renderArrayAsCards(objective.target_returns, "Target Returns")}

        {/* Missing Fields */}
        {objective.missing_fields && objective.missing_fields.length > 0 && (
          <div className="bg-yellow-500/10 rounded-lg p-4 border border-yellow-500/20">
            <h3 className="text-sm font-medium text-yellow-400 mb-2">Missing Fields</h3>
            <ul className="list-disc list-inside space-y-1">
              {objective.missing_fields.map((field, index) => (
                <li key={index} className="text-sm text-yellow-300">
                  {field}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Metadata */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4 border-t border-white/10">
          <div>
            <h3 className="text-sm font-medium text-white/60 mb-1">Created At</h3>
            <p className="text-sm text-white/80">{formatDate(objective.created_at)}</p>
          </div>
          <div>
            <h3 className="text-sm font-medium text-white/60 mb-1">Updated At</h3>
            <p className="text-sm text-white/80">{formatDate(objective.updated_at)}</p>
          </div>
        </div>

        {/* Source */}
        {objective.source && (
          <div className="text-sm text-white/60">
            <span className="font-medium">Source:</span> {objective.source}
          </div>
        )}
      </div>
    </div>
  )
}

