import { useState } from "react"
import { submitObjectiveIntake, formatFieldName, type ObjectiveIntakeResponse } from "@/lib/objectiveIntake"
import { buildStructuredPayload, fieldExistsInPayload } from "@/lib/objectiveUtils"

type Message = {
	id: string
	content: string
	isUser: boolean
	timestamp: Date
}

interface UseObjectiveChatProps {
	context: Record<string, string | number>
	missingFields: string[]
	currentFieldIndex: number
	updateField: (field: string, value: string | number) => void
	clearFields: () => void
	updateMissingFields: (fields: string[]) => void
	setCurrentFieldIndex: (index: number) => void
	getCurrentField: (lastResponse: ObjectiveIntakeResponse | null) => string | null
	findNextFieldIndex: (updatedContext: Record<string, string | number>, lastResponse: ObjectiveIntakeResponse | null) => number
	setContext: (context: Record<string, string | number>) => void
}

export function useObjectiveChat(fieldHelpers: UseObjectiveChatProps) {
	const [messages, setMessages] = useState<Message[]>([])
	const [isProcessing, setIsProcessing] = useState(false)
	const [objectiveId, setObjectiveId] = useState<string | null>(null)
	const [lastResponse, setLastResponse] = useState<ObjectiveIntakeResponse | null>(null)
	const [objectiveName, setObjectiveName] = useState<string>("")
	const [userAge, setUserAge] = useState<number | null>(null)
	// Generate a unique session ID once when the hook initializes
	const [sessionId] = useState<string>(() => `chat_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`)

	const addMessage = (content: string, isUser: boolean) => {
		setMessages((prev) => [
			...prev,
			{
				id: `${Date.now()}-${Math.random()}`,
				content,
				isUser,
				timestamp: new Date(),
			},
		])
	}

	const handleApiCall = async (
		transcript?: string,
		structuredPayload?: Record<string, any>
	) => {
		// Validate required fields
		if (!objectiveName.trim()) {
			addMessage("Error: Please provide an objective name before sending.", false)
			return
		}
		if (!userAge || userAge < 1 || userAge > 120) {
			addMessage("Error: Please provide a valid age (1-120) before sending.", false)
			return
		}

		setIsProcessing(true)

		try {
			// Build request payload matching Postman structure exactly
			const requestPayload: any = {
				name: objectiveName,
				source: "investment_chatbot",
				metadata: {
					source: "chatbot_conversation",
					session_id: sessionId,
					user_age: userAge,
				},
			}

			// Add optional fields only if they exist
			if (objectiveId) {
				requestPayload.objective_id = objectiveId
			}

			if (transcript) {
				requestPayload.transcript = transcript
			}

			if (structuredPayload) {
				requestPayload.structured_payload = structuredPayload
			}

			console.log("🔵 [handleApiCall] Sending request to API:", {
				url: "/api/objectives/intake",
				payload: requestPayload,
			})

			const response = await submitObjectiveIntake(requestPayload)

			setObjectiveId(response.objective_id)
			setLastResponse(response)

			console.log("🔵 [handleApiCall] API Response:", {
				status: response.status,
				missing_fields: response.missing_fields,
				structured_payload: response.structured_payload,
				objective_id: response.objective_id,
			})

			if (response.status === "complete") {
				addMessage(
					response.message ||
					"I got everything needed from the text, thank you. Your objective has been finalized and your portfolio has been rebalanced.",
					false,
				)
				if (response.allocation) {
					const allocationMsg = `Portfolio allocation completed. Expected return: ${response.allocation.expected_return
						? `${(response.allocation.expected_return * 100).toFixed(2)}%`
						: "N/A"
						}`
					addMessage(allocationMsg, false)
				}

				try {
					const { enableAITradingSubscription } = await import("@/lib/objectiveIntake")
					const subscriptionResult = await enableAITradingSubscription()
					if (subscriptionResult.success) {
						addMessage(
							"✅ AI trading has been enabled! Your trading agent will now automatically execute trades based on market signals and your investment objectives.",
							false,
						)
					} else {
						addMessage(
							`Note: ${subscriptionResult.message || "AI trading subscription could not be enabled automatically. You can enable it manually in your settings."}`,
							false,
						)
					}
				} catch (error) {
					console.error("Failed to enable AI trading subscription:", error)
				}

				fieldHelpers.clearFields()
			} else {
				// Show warnings first (if any) - but only if they're not just "Field required" duplicates
				const uniqueWarnings = [...new Set(response.warnings)]
				if (uniqueWarnings.length > 0) {
					uniqueWarnings.forEach((warning) => {
						// Skip generic "Field required" warnings as we'll show specific field request
						if (warning.toLowerCase() !== "field required") {
							addMessage(`Note: ${warning}`, false)
						}
					})
				}

				if (response.missing_fields.length > 0) {
					console.log("🟡 [handleApiCall] Processing missing_fields:", {
						api_missing_fields: response.missing_fields,
						context: fieldHelpers.context,
						structured_payload_keys: response.structured_payload ? Object.keys(response.structured_payload) : [],
					})

					// Clear any fields from context that are now in structured_payload
					// (meaning API accepted them)
					const fieldsInContext = Object.keys(fieldHelpers.context)
					const fieldsToRemove: string[] = []
					fieldsInContext.forEach((field) => {
						if (response.structured_payload) {
							const existsInPayload = fieldExistsInPayload(field, response.structured_payload)
							if (existsInPayload) {
								// Field is now in structured_payload - API accepted it, remove from context
								fieldsToRemove.push(field)
								const updatedContext = { ...fieldHelpers.context }
								delete updatedContext[field]
								fieldHelpers.setContext(updatedContext)
							}
						}
					})
					if (fieldsToRemove.length > 0) {
						console.log("🟣 [handleApiCall] Removing fields from context (now in structured_payload):", fieldsToRemove)
					}

					// Get the current field to ask for
					// getCurrentField uses the API response's missing_fields as source of truth
					const currentField = fieldHelpers.getCurrentField(response)
					console.log("🟢 [handleApiCall] getCurrentField returned:", currentField)

					if (currentField) {
						// Only show the single field the API actually needs
						addMessage(
							`I need some additional information. Please provide: ${formatFieldName(currentField)}`,
							false,
						)
					} else {
						// No field to ask for - either all are collected or all are in structured_payload
						console.log("🔴 [handleApiCall] No current field - all fields collected or in structured_payload")
					}
				} else {
					console.log("🟢 [handleApiCall] No missing_fields - clearing all fields")
					fieldHelpers.clearFields()
				}
			}
		} catch (error) {
			const errorMessage =
				error instanceof Error ? error.message : "An error occurred. Please try again."
			addMessage(`Error: ${errorMessage}`, false)
		} finally {
			setIsProcessing(false)
		}
	}

	const handleSend = async (text: string) => {
		if (!text.trim()) return

		addMessage(text, true)

		// User provides string only - send it directly as transcript
		const transcriptText = text.trim()

		// If no missing fields from API, send transcript to API
		const apiMissingFields = lastResponse?.missing_fields || []
		console.log("🔵 [handleSend] Called with text:", transcriptText.substring(0, 50))
		console.log("🔵 [handleSend] State:", {
			apiMissingFields,
			storedMissingFields: fieldHelpers.missingFields,
			context: fieldHelpers.context,
		})

		if (apiMissingFields.length === 0 && fieldHelpers.missingFields.length === 0) {
			console.log("🟢 [handleSend] No missing fields - sending transcript to API")
			await handleApiCall(transcriptText)
			return
		}

		// We have missing fields - collect them one by one
		// Get the current field from the API's missing_fields list
		const currentField = fieldHelpers.getCurrentField(lastResponse)
		console.log("🟢 [handleSend] Current field to collect:", currentField)

		if (currentField) {
			const updatedContext = { ...fieldHelpers.context, [currentField]: text }
			console.log("🟢 [handleSend] Updating context:", {
				field: currentField,
				value: text,
				updatedContext,
			})
			fieldHelpers.setContext(updatedContext)

			// Immediately send to API with this field to get updated missing_fields
			// This ensures we only ask for fields the API actually needs
			const structuredPayload = buildStructuredPayload(updatedContext, apiMissingFields, lastResponse)
			console.log("🟢 [handleSend] Sending structured payload:", structuredPayload)
			await handleApiCall(undefined, structuredPayload)
		} else {
			console.log("🔴 [handleSend] No current field - sending what we have")
			// No current field means we've collected everything or something went wrong
			// Send what we have to the API
			const structuredPayload = buildStructuredPayload(fieldHelpers.context, apiMissingFields, lastResponse)
			fieldHelpers.clearFields()
			await handleApiCall(undefined, structuredPayload)
		}
	}

	const handleFieldSubmit = async (value: string | number) => {
		const fieldToSubmit = fieldHelpers.getCurrentField(lastResponse)
		console.log("🔵 [handleFieldSubmit] Called with:", { fieldToSubmit, value })
		if (!fieldToSubmit) {
			console.log("🔴 [handleFieldSubmit] No field to submit")
			return
		}

		addMessage(`${formatFieldName(fieldToSubmit)}: ${value}`, true)

		const updatedContext = { ...fieldHelpers.context, [fieldToSubmit]: value }
		console.log("🟢 [handleFieldSubmit] Updating context:", {
			field: fieldToSubmit,
			value,
			updatedContext,
		})
		fieldHelpers.setContext(updatedContext)

		// Use API's missing_fields as source of truth
		const apiMissingFields = lastResponse?.missing_fields || []

		// Build structured payload with the field we just collected
		const structuredPayload = buildStructuredPayload(updatedContext, apiMissingFields, lastResponse)
		console.log("🟢 [handleFieldSubmit] Sending structured payload:", structuredPayload)

		// Immediately send to API to get updated missing_fields list
		// This ensures we only ask for fields the API actually needs
		await handleApiCall(undefined, structuredPayload)
	}

	return {
		messages,
		isProcessing,
		lastResponse,
		handleSend,
		handleFieldSubmit,
		setObjectiveName,
		setUserAge,
		objectiveName,
		userAge,
	}
}

