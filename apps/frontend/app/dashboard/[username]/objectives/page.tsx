"use client"

import { useEffect, useRef, useState } from "react"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { useAuth } from "@/hooks/useAuth"
import { useParams } from "next/navigation"
import { ChatMessage } from "@/components/objectives/ChatMessage"
import { ThinkingMessage } from "@/components/objectives/ThinkingMessage"
import { UserInputBar } from "@/components/objectives/UserInputBar"
import { FieldInput } from "@/components/objectives/FieldInput"
import {
  submitObjectiveIntake,
  formatFieldName,
  type ObjectiveIntakeResponse,
} from "@/lib/objectiveIntake"

type Message = {
  id: string
  content: string
  isUser: boolean
  timestamp: Date
}

export default function ObjectivesPage() {
  const params = useParams()
  const username = params.username as string
  const { user: authUser, loading: authLoading } = useAuth()

  const [messages, setMessages] = useState<Message[]>([])
  const [context, setContext] = useState<Record<string, string | number>>({})
  const [currentFieldIndex, setCurrentFieldIndex] = useState(0)
  const [isProcessing, setIsProcessing] = useState(false)
  const [objectiveId, setObjectiveId] = useState<string | null>(null)
  const [missingFields, setMissingFields] = useState<string[]>([])
  const [lastResponse, setLastResponse] = useState<ObjectiveIntakeResponse | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const chatContainerRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, isProcessing])

  const deepMerge = (target: Record<string, any>, source: Record<string, any>): Record<string, any> => {
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

  const removeFieldFromPayload = (
    payload: Record<string, any>,
    fieldName: string,
  ): void => {
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

  const fieldExistsInPayload = (
    fieldName: string,
    payload: Record<string, any>,
  ): boolean => {
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

  const buildStructuredPayload = (
    context: Record<string, string | number>,
    missingFieldsList: string[],
    lastResponseData: ObjectiveIntakeResponse | null,
  ): Record<string, any> => {
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

  const getCurrentField = () => {
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
    structuredPayload?: Record<string, any>,
  ) => {
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
      
      if (response.status === "complete") {
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
        setContext({})
        setCurrentFieldIndex(0)
        setMissingFields([])
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
          
          setContext((prev) => {
            const updated = { ...prev }
            response.missing_fields.forEach((field) => {
              if (updated[field]) {
                delete updated[field]
              }
            })
            return updated
          })
          
          setMissingFields(response.missing_fields)
          setCurrentFieldIndex(0)
        } else {
          setMissingFields([])
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

    if (missingFields.length === 0) {
      await handleApiCall(text)
    } else {
      const currentField = missingFields[currentFieldIndex]
      if (currentField) {
        const updatedContext = { ...context, [currentField]: text }
        setContext(updatedContext)

        if (currentFieldIndex < missingFields.length - 1) {
          setCurrentFieldIndex(currentFieldIndex + 1)
        } else {
          const structuredPayload = buildStructuredPayload(updatedContext, [], lastResponse)
          setContext({})
          setCurrentFieldIndex(0)
          setMissingFields([])
          await handleApiCall(undefined, structuredPayload)
        }
      }
    }
  }

  const handleFieldSubmit = async (value: string | number) => {
    const fieldToSubmit = getCurrentField()
    if (!fieldToSubmit) return

    addMessage(`${formatFieldName(fieldToSubmit)}: ${value}`, true)

    const updatedContext = { ...context, [fieldToSubmit]: value }
    setContext(updatedContext)
    
    const fieldIndex = missingFields.indexOf(fieldToSubmit)
    let nextIndex = fieldIndex + 1
    
    while (nextIndex < missingFields.length) {
      const nextField = missingFields[nextIndex]
      if (!updatedContext[nextField]) {
        const existsInPayload = lastResponse?.structured_payload
          ? fieldExistsInPayload(nextField, lastResponse.structured_payload)
          : false
        if (!existsInPayload) {
          setCurrentFieldIndex(nextIndex)
          return
        }
      }
      nextIndex++
    }
    
    const structuredPayload = buildStructuredPayload(updatedContext, [], lastResponse)
    setContext({})
    setCurrentFieldIndex(0)
    setMissingFields([])
    await handleApiCall(undefined, structuredPayload)
  }

  if (authLoading || !authUser) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0c0c0c] text-[#fafafa]">
        <div className="text-white/60">Loading...</div>
      </div>
    )
  }

  const currentField = getCurrentField()
  const showFieldInput = currentField && !isProcessing

  return (
    <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
      <DashboardHeader
        userName={authUser.firstName}
        username={username}
        userRole={authUser.role}
      />
      <Container className="max-w-6xl space-y-6 py-8">
        <PageHeading
          title="Objectives"
          tagline="Manage your trading objectives and goals."
        />

        <div className="flex flex-col h-[calc(100vh-250px)] border border-white/10 rounded-lg bg-black/20 overflow-hidden">
          <div
            ref={chatContainerRef}
            className="flex-1 overflow-y-auto p-6 space-y-4"
          >
            {messages.length === 0 && (
              <div className="text-center text-white/60 py-12">
                <p className="text-lg mb-2">Welcome! How can I help you today?</p>
                <p className="text-sm">
                  You can type your investment objectives or upload a .txt file with your requirements.
                </p>
              </div>
            )}

            {messages.map((message) => (
              <ChatMessage
                key={message.id}
                content={message.content}
                isUser={message.isUser}
              />
            ))}

            {isProcessing && <ThinkingMessage />}

            {showFieldInput && (
              <div className="mt-4">
                <FieldInput
                  fieldName={currentField}
                  onSubmit={handleFieldSubmit}
                  disabled={isProcessing}
                />
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          <div className="border-t border-white/10 p-4 bg-black/30">
            <UserInputBar
              onSend={handleSend}
              disabled={isProcessing || !!showFieldInput}
              placeholder={
                showFieldInput
                  ? "Please complete the field above first..."
                  : "Type your message or upload a .txt file..."
              }
            />
          </div>
        </div>
      </Container>
    </div>
  )
}

