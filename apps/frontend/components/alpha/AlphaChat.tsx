"use client"

import { FormEvent, useEffect, useRef, useState } from "react"
import { AnimatePresence, motion, type Variants } from "framer-motion"
import { Send } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { ChatMessage } from "@/mock/alphaData"
import { chatMessages } from "@/mock/alphaData"

const messageVariants: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.25, ease: [0.16, 1, 0.3, 1] } },
  exit: { opacity: 0, y: -12, transition: { duration: 0.2, ease: [0.16, 1, 0.3, 1] } },
}

const assistantReplies = [
  "Let's map out entry/exit rules, filters, and risk parameters next.",
  "Consider scoring the alpha with Sharpe and Sortino before deploying live.",
  "Would you like to simulate this against the last 3 months of market regimes?",
]

type AlphaChatProps = {
  className?: string
}

export function AlphaChat({ className }: AlphaChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(chatMessages)
  const [input, setInput] = useState("")
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages])

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [])

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (!input.trim()) return

    const userMessage = {
      id: `msg-${Date.now()}`,
      role: "user" as const,
      content: input.trim(),
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    }

    setMessages((prev: ChatMessage[]) => [...prev, userMessage])
    setInput("")

    const reply =
      assistantReplies[Math.floor(Math.random() * assistantReplies.length)] ??
      assistantReplies[0]

    timeoutRef.current = setTimeout(() => {
      setMessages((prev: ChatMessage[]) => [
        ...prev,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant" as const,
          content: reply,
          time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        },
      ])
    }, 600)
  }

  return (
    <Card className={cn("card-glass neon-hover flex h-full flex-col border border-white/10 bg-black/50 shadow-xl", className)}>
      <CardHeader>
        <CardTitle className="h-title text-2xl text-white font-playfair">Generate Alpha Ideas</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col overflow-hidden">
        <div
          ref={scrollRef}
          className="no-scrollbar flex-1 space-y-3 overflow-y-auto rounded-xl border border-white/10 bg-black/40 p-4"
        >
          <AnimatePresence initial={false}>
            {messages.map((message: ChatMessage) => {
              const isUser = message.role === "user"
              return (
                <motion.div
                  key={message.id}
                  variants={messageVariants}
                  initial="hidden"
                  animate="show"
                  exit="exit"
                  className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm shadow-lg ${
                      isUser
                        ? "bg-emerald-500/20 text-emerald-100"
                        : "bg-white/10 text-white/90 backdrop-blur"
                    }`}
                  >
                    <p>{message.content}</p>
                    <span className="mt-2 block text-[11px] uppercase tracking-wider text-white/40">
                      {isUser ? "You" : "Alpha Assistant"} · {message.time}
                    </span>
                  </div>
                </motion.div>
              )
            })}
          </AnimatePresence>
        </div>
        <form onSubmit={handleSubmit} className="mt-4 flex items-center gap-3">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Draft an alpha idea..."
            className="flex-1 rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm text-white placeholder:text-white/40 focus:outline-none focus:ring-white/50"
          />
          <Button
            type="submit"
            className="flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
          >
            <Send className="size-4" />
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}


