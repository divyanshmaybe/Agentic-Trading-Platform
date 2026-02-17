import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

import { resolveHeadline } from "../notification-utils"
import type { KafkaNotification } from "../types"

export function NotificationHeader({
  notification,
  icon,
  title,
  iconWrapperClass,
  badgeClass,
}: {
  notification: KafkaNotification
  icon: ReactNode
  title: string
  iconWrapperClass?: string
  badgeClass?: string
}) {
  return (
    <header className="flex items-start justify-between gap-3">
      <div className="flex-1">
        <div className="flex items-center gap-3 text-xs font-semibold uppercase tracking-[0.3em] text-white/45">
          <span
            className={cn(
              "flex size-9 items-center justify-center rounded-xl border border-white/12 bg-white/5 text-white/65 shadow-[0_10px_30px_-18px_rgba(0,0,0,0.8)] transition-all duration-300 group-hover:shadow-[0_12px_32px_-16px_rgba(0,0,0,0.85)]",
              iconWrapperClass,
            )}
          >
            {icon}
          </span>
          <span className={cn("text-white/55", badgeClass)}>{title}</span>
        </div>
        <h3 className="mt-3 text-2xl font-semibold text-[#fafafa]">{resolveHeadline(notification)}</h3>
      </div>
    </header>
  )
}

