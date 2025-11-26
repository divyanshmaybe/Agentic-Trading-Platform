import { useRef, useEffect } from "react"
import { ChatMessage } from "./ChatMessage"
import { ThinkingMessage } from "./ThinkingMessage"
import { FieldInput } from "./FieldInput"
import { EmptyChatState } from "./EmptyChatState"

type Message = {
  id: string
  content: string
  isUser: boolean
  timestamp: Date
}

interface ChatContainerProps {
  messages: Message[]
  isProcessing: boolean
  currentField: string | null
  onFieldSubmit: (value: string | number) => Promise<void>
}

export function ChatContainer({ messages, isProcessing, currentField, onFieldSubmit }: ChatContainerProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const chatContainerRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, isProcessing])

  const showFieldInput = currentField && !isProcessing

  return (
    <div ref={chatContainerRef} className="flex-1 overflow-y-auto p-6 space-y-4">
      {messages.length === 0 && <EmptyChatState />}

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
            onSubmit={onFieldSubmit}
            disabled={isProcessing}
          />
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  )
}

