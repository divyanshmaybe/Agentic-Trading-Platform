import { useState } from "react"
import { fieldExistsInPayload } from "@/lib/objectiveUtils"
import type { ObjectiveIntakeResponse } from "@/lib/objectiveIntake"

export function useObjectiveFields() {
	const [context, setContext] = useState<Record<string, string | number>>({})
	const [currentFieldIndex, setCurrentFieldIndex] = useState(0)
	const [missingFields, setMissingFields] = useState<string[]>([])

	const getCurrentField = (lastResponse: ObjectiveIntakeResponse | null) => {
		// USE THE API RESPONSE'S missing_fields AS THE SOURCE OF TRUTH
		// The API returns an updated missing_fields array on each response
		// We should ONLY ask for fields that are in the current API response's missing_fields
		const apiMissingFields = lastResponse?.missing_fields || []

		console.log("🔵 [getCurrentField] Called with:", {
			storedMissingFields: missingFields,
			responseMissingFields: apiMissingFields,
			context,
			structured_payload: lastResponse?.structured_payload,
		})

		if (apiMissingFields.length === 0) {
			console.log("🔴 [getCurrentField] No missing fields in API response")
			return null
		}

		// Find the first field in the API's missing_fields list that:
		// 1. Is not in context (we haven't collected it yet)
		for (let i = 0; i < apiMissingFields.length; i++) {
			const field = apiMissingFields[i]

			// Skip if we've collected it in context (just sent to API, waiting for response)
			if (context[field]) {
				console.log(`⏭️ [getCurrentField] Skipping ${field} - exists in context:`, context[field])
				continue
			}

			// This is the field to ask for
			console.log(`🟢 [getCurrentField] Returning field: ${field}`)
			return field
		}
		console.log("🔴 [getCurrentField] No field found after iterating")
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
		// Store the original missing_fields list ONLY ONCE
		// This list is returned by the API only once and should never be updated
		// We'll filter it dynamically based on structured_payload when determining what to ask for
		// Don't clear context here - that's handled in handleApiCall based on structured_payload
		if (missingFields.length === 0) {
			// Only store if we don't have it yet (first time)
			console.log("🟢 [updateMissingFields] Storing original missing_fields:", fields)
			setMissingFields(fields)
		} else {
			console.log("🟠 [updateMissingFields] Already have missing_fields, NOT updating. Current:", missingFields, "New:", fields)
		}
		// If we already have it, don't update it - keep using the original list
	}

	const findNextFieldIndex = (updatedContext: Record<string, string | number>, lastResponse: ObjectiveIntakeResponse | null) => {
		// ONLY use missing_fields from the latest API response - this is the source of truth
		const apiMissingFields = lastResponse?.missing_fields || []

		if (apiMissingFields.length === 0) return -1

		const fieldToSubmit = getCurrentField(lastResponse)
		if (!fieldToSubmit) return -1

		const fieldIndex = apiMissingFields.indexOf(fieldToSubmit)
		let nextIndex = fieldIndex + 1

		// Only iterate through fields that are in the API's missing_fields list
		while (nextIndex < apiMissingFields.length) {
			const nextField = apiMissingFields[nextIndex]
			// Only consider fields we haven't collected
			if (!updatedContext[nextField]) {
				return nextIndex
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
