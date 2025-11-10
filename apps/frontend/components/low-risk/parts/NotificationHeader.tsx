import type { ReactNode } from "react"

import { resolveHeadline } from "../notification-utils"
import type { KafkaNotification } from "../types"

export function NotificationHeader({
  notification,
  icon,
  title,
}: {
  notification: KafkaNotification
  icon: ReactNode
  title: string
}) {
  return (
    <header className="flex items-start justify-between gap-3">
      <div>
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.3em] text-white/55">
          <span className="text-white/70">{icon}</span>
          <span>{title}</span>
        </div>
        <h3 className="mt-3 text-lg font-semibold text-[#fafafa]">{resolveHeadline(notification)}</h3>
      </div>
      <NotificationMeta notification={notification} />
    </header>
  )
}

function NotificationMeta({ notification }: { notification: KafkaNotification }) {
  if (!notification.topic && !notification.timestamp) {
    return null
  }

  return (
    <div className="text-right text-[11px] text-white/55">
      <div className="font-semibold uppercase tracking-[0.25em]">Topic</div>
      <div className="mt-1 max-w-[12ch] overflow-hidden text-ellipsis whitespace-nowrap font-mono text-white/70">
        {notification.topic ?? "live_stream"}
      </div>
      <div className="mt-2 font-semibold uppercase tracking-[0.25em] text-white/45">Time</div>
      <div className="mt-1 text-white/70">{notification.timestamp}</div>
    </div>
  )
}

