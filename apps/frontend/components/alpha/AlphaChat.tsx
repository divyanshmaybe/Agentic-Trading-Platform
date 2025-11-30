"use client"

import { FormEvent, useEffect, useRef, useState } from "react"
import { AnimatePresence, motion, type Variants } from "framer-motion"
import { Loader2, Send, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

const messageVariants: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.25, ease: [0.16, 1, 0.3, 1] } },
  exit: { opacity: 0, y: -12, transition: { duration: 0.2, ease: [0.16, 1, 0.3, 1] } },
}

type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  time: string
}

const ALPHACOPILOT_URL = process.env.NEXT_PUBLIC_ALPHACOPILOT_URL || "http://localhost:8069"

const initialMessages: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    content:
      "Welcome to AlphaCopilot! Share your trading hypothesis and I'll help you generate factor expressions. For example: 'Stocks with increasing momentum and decreasing volatility tend to outperform.'",
    time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  },
]

type AlphaChatProps = {
  className?: string
}

export function AlphaChat({ className }: AlphaChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages)
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages])

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!input.trim() || isLoading) return

    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: input.trim(),
      time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput("")
    setIsLoading(true)

    try {
      // Create a research run with the hypothesis
      const response = await fetch(`${ALPHACOPILOT_URL}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hypothesis: userMessage.content,
          max_iterations: 1, // Quick single iteration for chat
          num_runs: 1,
        }),
      })

      if (!response.ok) {
        throw new Error("Failed to create run")
      }

      const data = await response.json()
      const run = data.runs?.[0]

      if (run) {
        // Add assistant response
        const assistantMessage: ChatMessage = {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: `I've started analyzing your hypothesis. Research run created (ID: ${run.id.slice(0, 8)}...). 

Check the "Research Runs" tab to monitor progress and see the generated factors once complete.

Would you like to:
• Refine the hypothesis with more specific conditions?
• Specify particular sectors or market caps?
• Add risk constraints or holding periods?`,
          time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        }
        setMessages((prev) => [...prev, assistantMessage])
      }
    } catch (error) {
      console.error("Failed to create research run:", error)
      
      // Fallback to local response if server is unavailable
      const fallbackMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: `Great hypothesis! To convert this into tradeable factors, I'd suggest:

1. **Momentum Factor**: \`DELTA($close, 20) / $close\` - 20-day price change
2. **Volatility Factor**: \`STDDEV($close, 20) / SMA($close, 20)\` - Normalized volatility
3. **Volume Confirmation**: \`$volume / SMA($volume, 20)\` - Volume ratio

Would you like me to start a full research run with these factors? Click "New Research" to begin backtesting.`,
        time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      }
      setMessages((prev) => [...prev, fallbackMessage])
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card
      className={cn(
        "card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur",
        className
      )}
    >
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-2xl font-playfair text-[#fafafa]">
          <Sparkles className="size-5 text-violet-400" />
          Alpha Ideas
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col overflow-hidden">
        <div
          ref={scrollRef}
          className="no-scrollbar flex-1 space-y-3 overflow-y-auto rounded-xl border border-white/10 bg-black/25 p-4"
        >
          <AnimatePresence initial={false}>
            {messages.map((message) => {
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
                        ? "bg-violet-500/20 text-violet-100"
                        : "bg-white/10 text-white/90 backdrop-blur"
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{message.content}</p>
                    <span className="mt-2 block text-[11px] uppercase tracking-wider text-white/40">
                      {isUser ? "You" : "AlphaCopilot"} · {message.time}
                    </span>
                  </div>
                </motion.div>
              )
            })}
            {isLoading && (
              <motion.div
                variants={messageVariants}
                initial="hidden"
                animate="show"
                className="flex w-full justify-start"
              >
                <div className="flex items-center gap-2 rounded-2xl bg-white/10 px-4 py-3 text-sm shadow-lg backdrop-blur">
                  <Loader2 className="size-4 animate-spin text-violet-400" />
                  <span className="text-white/60">Analyzing hypothesis...</span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <form onSubmit={handleSubmit} className="mt-4 flex items-center gap-3">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Describe your trading hypothesis..."
            disabled={isLoading}
            className="flex-1 rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-violet-400/50 disabled:opacity-50"
          />
          <Button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="flex items-center gap-2 rounded-xl border border-violet-500/40 bg-violet-500/20 text-violet-100 hover:border-violet-400/50 hover:bg-violet-500/30 disabled:opacity-50"
          >
            {isLoading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Send className="size-4" />
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
