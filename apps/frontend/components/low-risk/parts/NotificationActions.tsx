import { cn } from "@/lib/utils"

import type { KafkaNotificationAction } from "../types"

export function NotificationActions({ actions }: { actions: KafkaNotificationAction[] | undefined }) {
  if (!actions?.length) {
    return null
  }

  return (
    <footer className="mt-4 flex flex-wrap gap-2">
      {actions.map((action, index) => (
        <NotificationAction key={`${action.value}-${index}`} action={action} primary={index === 0} />
      ))}
    </footer>
  )
}

function NotificationAction({ action, primary }: { action: KafkaNotificationAction; primary: boolean }) {
  const className = cn(
    "rounded-lg px-3 py-2 text-xs font-semibold uppercase tracking-[0.25em] transition-all duration-200",
    primary
      ? "border border-emerald-400/40 bg-emerald-500/15 text-emerald-200 hover:border-emerald-300/70 hover:bg-emerald-500/30"
      : "border border-white/15 bg-white/5 text-white/70 hover:bg-white/12 hover:text-white",
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

