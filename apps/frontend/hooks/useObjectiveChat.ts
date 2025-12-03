import { useState, useEffect, useCallback } from "react"
import { submitObjectiveIntake, formatFieldName, getObjectiveByUserId, type ObjectiveIntakeResponse, type ObjectiveResponse } from "@/lib/objectiveIntake"
import { buildStructuredPayload } from "@/lib/objectiveUtils"

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
  const [objective, setObjective] = useState<ObjectiveResponse | null>(null)
  const [isFetchingObjective, setIsFetchingObjective] = useState(false)

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

  const fetchObjective = useCallback(async () => {
    setIsFetchingObjective(true)
    try {
      const fetchedObjective = await getObjectiveByUserId()
      if (fetchedObjective) {
        setObjective(fetchedObjective)
        setObjectiveId(fetchedObjective.id)
      } else {
        setObjective(null)
      }
    } catch (error) {
      console.error("Failed to fetch objective:", error)
      setObjective(null)
    } finally {
      setIsFetchingObjective(false)
    }
  }, [])

  const handleApiCall = async (transcript?: string, structuredPayload?: Record<string, any>) => {
    setIsProcessing(true)

    try {
      const response = await submitObjectiveIntake({
        objective_id: objectiveId,
        transcript: transcript || undefined,
        structured_payload: structuredPayload || undefined,
        source: "chatbot",
      })

      setObjectiveId(response.objective_id)
      setLastResponse(response)
      
      // Fetch objective when status becomes complete
      if (response.status === "complete") {
        await fetchObjective()
        addMessage(
          response.message ||
            "I got everything needed from the text, thank you. Your objective has been finalized and your portfolio has been rebalanced.",
          false,
        )
        if (response.allocation) {
          const allocationMsg = `Portfolio allocation completed. Expected return: ${
            response.allocation.expected_return
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
        if (response.message) {
          addMessage(response.message, false)
        }
        
        if (response.warnings.length > 0) {
          response.warnings.forEach((warning) => {
            addMessage(`Note: ${warning}`, false)
          })
        }
        
        if (response.missing_fields.length > 0) {
          addMessage(
            `I need some additional information. Please provide the following: ${response.missing_fields.join(", ")}`,
            false,
          )
          fieldHelpers.updateMissingFields(response.missing_fields)
        } else {
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

    if (fieldHelpers.missingFields.length === 0) {
      await handleApiCall(text)
    } else {
      const currentField = fieldHelpers.missingFields[fieldHelpers.currentFieldIndex]
      if (currentField) {
        const updatedContext = { ...fieldHelpers.context, [currentField]: text }
        fieldHelpers.setContext(updatedContext)

        if (fieldHelpers.currentFieldIndex < fieldHelpers.missingFields.length - 1) {
          fieldHelpers.setCurrentFieldIndex(fieldHelpers.currentFieldIndex + 1)
        } else {
          const structuredPayload = buildStructuredPayload(updatedContext, [], lastResponse)
          fieldHelpers.clearFields()
          await handleApiCall(undefined, structuredPayload)
        }
      }
    }
  }

  const handleFieldSubmit = async (value: string | number) => {
    const fieldToSubmit = fieldHelpers.getCurrentField(lastResponse)
    if (!fieldToSubmit) return

    addMessage(`${formatFieldName(fieldToSubmit)}: ${value}`, true)

    const updatedContext = { ...fieldHelpers.context, [fieldToSubmit]: value }
    fieldHelpers.setContext(updatedContext)
    
    const nextIndex = fieldHelpers.findNextFieldIndex(updatedContext, lastResponse)
    
    if (nextIndex !== -1) {
      fieldHelpers.setCurrentFieldIndex(nextIndex)
      return
    }
    
    const structuredPayload = buildStructuredPayload(updatedContext, [], lastResponse)
    fieldHelpers.clearFields()
    await handleApiCall(undefined, structuredPayload)
  }

  // Fetch objective on mount if not already loaded
  useEffect(() => {
    if (!objective && !isFetchingObjective) {
      fetchObjective()
    }
  }, [objective, isFetchingObjective, fetchObjective])

  return {
    messages,
    isProcessing,
    lastResponse,
    objectiveId,
    objective,
    isFetchingObjective,
    fetchObjective,
    handleSend,
    handleFieldSubmit,
  }
}

