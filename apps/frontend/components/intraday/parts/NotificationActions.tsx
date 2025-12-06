import { useState } from "react"

import { cn } from "@/lib/utils"

import type { KafkaNotificationAction, KafkaNotification } from "../types"
import { TradeModal } from "./TradeModal"

export function NotificationActions({
  actions,
  signal,
  notification,
}: {
  actions: KafkaNotificationAction[] | undefined
  signal: number | null
  notification: KafkaNotification
}) {
  const [tradeModalOpen, setTradeModalOpen] = useState(false)
  const [tradeSide, setTradeSide] = useState<"BUY" | "SELL">("BUY")

  // Filter out "review filing" button for nse-signal notifications
  const filteredActions = notification.type === "nse-signal"
    ? actions?.filter((action) => !action.label.toLowerCase().includes("review filing"))
    : actions

  return (
    <>
      <footer className="mt-4 flex flex-wrap items-center gap-2">
        {signal === 1 && (
          <button
            type="button"
            onClick={() => {
              setTradeSide("BUY")
              setTradeModalOpen(true)
            }}
            className={cn(
              "inline-flex items-center justify-center rounded-lg px-3 py-2 text-xs font-semibold uppercase tracking-[0.25em] transition-all duration-200",
              "border border-emerald-400/30 bg-emerald-500/15 text-emerald-200 shadow-[0_10px_28px_-18px_rgba(16,185,129,0.35)] hover:-translate-y-0.5 hover:border-emerald-300/50 hover:bg-emerald-500/25 hover:text-emerald-100",
            )}
          >
            Buy
          </button>
        )}
        {signal != null && signal !== 1 && signal !== 0 && (
          <button
            type="button"
            onClick={() => {
              setTradeSide("SELL")
              setTradeModalOpen(true)
            }}
            className={cn(
              "inline-flex items-center justify-center rounded-lg px-3 py-2 text-xs font-semibold uppercase tracking-[0.25em] transition-all duration-200",
              "border border-red-400/30 bg-red-500/15 text-red-200 shadow-[0_10px_28px_-18px_rgba(248,113,113,0.35)] hover:-translate-y-0.5 hover:border-red-300/50 hover:bg-red-500/25 hover:text-red-100",
            )}
          >
            Sell
          </button>
        )}
        {filteredActions?.map((action, index) => (
          <NotificationAction
            key={`${action.value}-${index}`}
            action={action}
            primary={index === 0}
            signal={signal}
          />
        ))}
      </footer>
      <TradeModal
        open={tradeModalOpen}
        onOpenChange={setTradeModalOpen}
        notification={notification}
        side={tradeSide}
      />
    </>
  )
}

function NotificationAction({
  action,
  primary,
  signal,
}: {
  action: KafkaNotificationAction
  primary: boolean
  signal: number | null
}) {
  // Determine button colors based on signal strength
  const buttonClassName =
    signal === 1
      ? primary
        ? "border border-emerald-400/50 bg-emerald-500/25 text-emerald-100 shadow-[0_12px_32px_-18px_rgba(16,185,129,0.45)] hover:-translate-y-0.5 hover:border-emerald-300/70 hover:bg-emerald-500/35 hover:text-emerald-50"
        : "border border-emerald-400/30 bg-emerald-500/15 text-emerald-200 shadow-[0_10px_28px_-18px_rgba(16,185,129,0.35)] hover:-translate-y-0.5 hover:border-emerald-300/50 hover:bg-emerald-500/25 hover:text-emerald-100"
      : signal === 0
        ? primary
          ? "border border-amber-400/50 bg-amber-500/25 text-amber-100 shadow-[0_12px_32px_-18px_rgba(250,204,21,0.45)] hover:-translate-y-0.5 hover:border-amber-300/70 hover:bg-amber-500/35 hover:text-amber-50"
          : "border border-amber-400/30 bg-amber-500/15 text-amber-200 shadow-[0_10px_28px_-18px_rgba(250,204,21,0.35)] hover:-translate-y-0.5 hover:border-amber-300/50 hover:bg-amber-500/25 hover:text-amber-100"
        : signal != null && signal !== 1 && signal !== 0
          ? primary
            ? "border border-red-400/50 bg-red-500/25 text-red-100 shadow-[0_12px_32px_-18px_rgba(248,113,113,0.45)] hover:-translate-y-0.5 hover:border-red-300/70 hover:bg-red-500/35 hover:text-red-50"
            : "border border-red-400/30 bg-red-500/15 text-red-200 shadow-[0_10px_28px_-18px_rgba(248,113,113,0.35)] hover:-translate-y-0.5 hover:border-red-300/50 hover:bg-red-500/25 hover:text-red-100"
          : primary
            ? "border border-emerald-400/40 bg-emerald-500/20 text-emerald-100 shadow-[0_12px_32px_-18px_rgba(16,185,129,0.45)] hover:-translate-y-0.5 hover:border-emerald-300/60 hover:bg-emerald-500/30 hover:text-emerald-50"
            : "border border-white/15 bg-white/5 text-white/70 shadow-[0_10px_28px_-18px_rgba(15,23,42,0.55)] hover:-translate-y-0.5 hover:border-white/20 hover:bg-white/12 hover:text-white"

  const className = cn(
    "inline-flex items-center justify-center rounded-lg px-3 py-2 text-xs font-semibold uppercase tracking-[0.25em] transition-all duration-200",
    buttonClassName,
  )

  if (action.href || action.value.startsWith("http")) {
    const href = action.href ?? action.value
    return (
      <a href={href} target="_blank" rel="noreferrer" className={className}>
        {action.label}
      </a>
    )
  }

  return (
    <button type="button" className={className} data-action={action.value}>
      {action.label}
    </button>
  )
}

