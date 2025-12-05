"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  formatFieldName,
  inferFieldType,
  getAllowedValues,
  type FieldType,
} from "@/lib/objectiveIntake"
import { cn } from "@/lib/utils"

type FieldInputProps = {
  fieldName: string
  onSubmit: (value: string | number) => void
  disabled?: boolean
}

export function FieldInput({ fieldName, onSubmit, disabled = false }: FieldInputProps) {
  const [value, setValue] = useState("")
  const fieldType = inferFieldType(fieldName)
  const displayName = formatFieldName(fieldName)
  const allowedValues = getAllowedValues(fieldName)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!value.trim()) return

    let processedValue: string | number
    if (fieldType === "number") {
      const numValue = parseFloat(value)
      if (isNaN(numValue)) {
        alert("Please enter a valid number")
        return
      }
      processedValue = numValue
    } else if (fieldType === "select" && allowedValues) {
      processedValue = value.trim()
      if (!allowedValues.includes(processedValue)) {
        alert(
          `Please select one of the allowed values: ${allowedValues.join(", ")}`
        )
        return
      }
    } else {
      processedValue = value.trim().toLowerCase()
    }

    onSubmit(processedValue)
    setValue("")
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg bg-white/8 backdrop-blur p-4 border border-white/10">
      <div>
        <p className="text-sm text-white/80">
          Please provide: <span className="font-semibold text-[#fafafa]">{displayName}</span>
        </p>
        {allowedValues && (
          <p className="text-xs text-white/60 mt-1">
            Allowed values: {allowedValues.join(", ")}
          </p>
        )}
      </div>
      <form onSubmit={handleSubmit} className="flex gap-2">
        {fieldType === "select" && allowedValues ? (
          <select
            value={value}
            onChange={(e) => setValue(e.target.value)}
            disabled={disabled}
            className={cn(
              "flex-1 rounded-lg border border-white/15 bg-white/8 px-4 py-2",
              "text-[#fafafa]",
              "focus:outline-none focus:ring-2 focus:ring-white/20 focus:border-white/30",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              "transition-all",
              "[&>option]:bg-[#0c0c0c] [&>option]:text-[#fafafa]"
            )}
          >
            <option value="">Select {displayName.toLowerCase()}...</option>
            {allowedValues.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        ) : (
          <input
            type={fieldType === "number" ? "number" : "text"}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            disabled={disabled}
            placeholder={`Enter ${displayName.toLowerCase()}...`}
            step={fieldType === "number" ? "any" : undefined}
            min={fieldName.toLowerCase() === "target_return" ? 1 : undefined}
            max={fieldName.toLowerCase() === "target_return" ? 999 : undefined}
            className={cn(
              "flex-1 rounded-lg border border-white/15 bg-white/8 px-4 py-2",
              "text-[#fafafa] placeholder:text-white/40",
              "focus:outline-none focus:ring-2 focus:ring-white/20 focus:border-white/30",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              "transition-all"
            )}
          />
        )}
        <Button
          type="submit"
          disabled={!value.trim() || disabled}
          className="px-6 bg-white/10 hover:bg-white/20 text-[#fafafa] border border-white/15"
        >
          Submit
        </Button>
      </form>
    </div>
  )
}

