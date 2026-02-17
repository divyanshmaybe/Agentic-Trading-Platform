"use client"

import { cn } from "@/lib/utils"

type ChatMessageProps = {
  content: string
  isUser: boolean
}

export function ChatMessage({ content, isUser }: ChatMessageProps) {
  return (
    <div
      className={cn(
        "flex w-full",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={cn(
          "max-w-[80%] rounded-lg px-4 py-3 text-sm",
          isUser
            ? "bg-white/8 text-[#fafafa]"
            : "bg-white/6 text-white/90"
        )}
      >
        <p className="whitespace-pre-wrap wrap-break-word">{content}</p>
      </div>
    </div>
  )
}

