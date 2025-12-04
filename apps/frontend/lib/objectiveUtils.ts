import type { ObjectiveIntakeResponse } from "@/lib/objectiveIntake"

export function deepMerge(target: Record<string, any>, source: Record<string, any>): Record<string, any> {
  const result = { ...target }
  for (const key in source) {
    if (source[key] && typeof source[key] === "object" && !Array.isArray(source[key])) {
      result[key] = deepMerge(result[key] || {}, source[key])
    } else {
      result[key] = source[key]
    }
  }
  return result
}

export function removeFieldFromPayload(payload: Record<string, any>, fieldName: string): void {
  if (fieldName.includes(".")) {
    const [parent, child] = fieldName.split(".")
    if (payload[parent] && typeof payload[parent] === "object") {
      delete payload[parent][child]
      if (Object.keys(payload[parent]).length === 0) {
        delete payload[parent]
      }
    }
  } else {
    delete payload[fieldName]
  }
}

export function fieldExistsInPayload(fieldName: string, payload: Record<string, any>): boolean {
  if (fieldName.includes(".")) {
    const [parent, child] = fieldName.split(".")
    return (
      payload[parent] &&
      typeof payload[parent] === "object" &&
      payload[parent][child] !== undefined &&
      payload[parent][child] !== null &&
      payload[parent][child] !== ""
    )
  }
  return (
    payload[fieldName] !== undefined &&
    payload[fieldName] !== null &&
    payload[fieldName] !== ""
  )
}

export function buildStructuredPayload(
  context: Record<string, string | number>,
  missingFieldsList: string[],
  lastResponseData: ObjectiveIntakeResponse | null,
): Record<string, any> {
  const structuredPayload: Record<string, any> = {}
  
  console.log("🔵 [buildStructuredPayload] Building payload:", {
    context,
    missingFieldsList,
    lastResponseData_structured_payload: lastResponseData?.structured_payload,
  })
  
  // Include ALL fields from context - we want to send what the user just provided
  // even if it's still in missingFieldsList (the API will update the list)
  Object.entries(context).forEach(([key, value]) => {
    if (key.includes(".")) {
      const [parent, child] = key.split(".")
      if (!structuredPayload[parent]) {
        structuredPayload[parent] = {}
      }
      structuredPayload[parent][child] = value
    } else {
      structuredPayload[key] = value
    }
  })

  if (lastResponseData?.structured_payload) {
    const basePayload = JSON.parse(JSON.stringify(lastResponseData.structured_payload))
    // Remove fields that are still missing (but keep what we just collected in context)
    missingFieldsList.forEach((field) => {
      // Only remove if it's not in our context (user hasn't provided it yet)
      if (!context[field]) {
        removeFieldFromPayload(basePayload, field)
      }
    })
    // Merge: context values override base payload, but base payload provides other existing values
    const merged = deepMerge(basePayload, structuredPayload)
    Object.assign(structuredPayload, merged)
  }

  console.log("🟢 [buildStructuredPayload] Final payload:", structuredPayload)
  return structuredPayload
}

