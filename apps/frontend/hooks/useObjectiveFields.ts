import { useState } from "react"
import { fieldExistsInPayload } from "@/lib/objectiveUtils"
import type { ObjectiveIntakeResponse } from "@/lib/objectiveIntake"

export function useObjectiveFields() {
  const [context, setContext] = useState<Record<string, string | number>>({})
  const [currentFieldIndex, setCurrentFieldIndex] = useState(0)
  const [missingFields, setMissingFields] = useState<string[]>([])

  const getCurrentField = (lastResponse: ObjectiveIntakeResponse | null) => {
    if (missingFields.length === 0) return null
    
    for (let i = currentFieldIndex; i < missingFields.length; i++) {
      const field = missingFields[i]
      if (!context[field]) {
        const existsInPayload = lastResponse?.structured_payload
          ? fieldExistsInPayload(field, lastResponse.structured_payload)
          : false
        if (!existsInPayload) {
          return field
        }
      }
    }
    return null
  }

  const updateField = (field: string, value: string | number) => {
    setContext((prev) => ({ ...prev, [field]: value }))
  }

  const clearFields = () => {
    setContext({})
    setCurrentFieldIndex(0)
    setMissingFields([])
  }

  const updateMissingFields = (fields: string[]) => {
    setContext((prev) => {
      const updated = { ...prev }
      fields.forEach((field) => {
        if (updated[field]) {
          delete updated[field]
        }
      })
      return updated
    })
    setMissingFields(fields)
    setCurrentFieldIndex(0)
  }

  const findNextFieldIndex = (updatedContext: Record<string, string | number>, lastResponse: ObjectiveIntakeResponse | null) => {
    const fieldToSubmit = getCurrentField(lastResponse)
    if (!fieldToSubmit) return -1

    const fieldIndex = missingFields.indexOf(fieldToSubmit)
    let nextIndex = fieldIndex + 1
    
    while (nextIndex < missingFields.length) {
      const nextField = missingFields[nextIndex]
      if (!updatedContext[nextField]) {
        const existsInPayload = lastResponse?.structured_payload
          ? fieldExistsInPayload(nextField, lastResponse.structured_payload)
          : false
        if (!existsInPayload) {
          return nextIndex
        }
      }
      nextIndex++
    }
    
    return -1
  }

  return {
    context,
    currentFieldIndex,
    missingFields,
    getCurrentField,
    updateField,
    clearFields,
    updateMissingFields,
    setCurrentFieldIndex,
    findNextFieldIndex,
    setContext,
  }
}

