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
  
  Object.entries(context).forEach(([key, value]) => {
    if (!missingFieldsList.includes(key)) {
      if (key.includes(".")) {
        const [parent, child] = key.split(".")
        if (!structuredPayload[parent]) {
          structuredPayload[parent] = {}
        }
        structuredPayload[parent][child] = value
      } else {
        structuredPayload[key] = value
      }
    }
  })

  if (lastResponseData?.structured_payload) {
    const basePayload = JSON.parse(JSON.stringify(lastResponseData.structured_payload))
    missingFieldsList.forEach((field) => {
      removeFieldFromPayload(basePayload, field)
    })
    const merged = deepMerge(basePayload, structuredPayload)
    Object.assign(structuredPayload, merged)
  }

  return structuredPayload
}

