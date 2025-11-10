"use client"

import { useMemo, useState, useCallback } from "react"
import { AnimatePresence, motion } from "framer-motion"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useNotificationStream } from "@/hooks/useNotificationStream"
import {
  coerceNotification,
  formatTemporal,
  resolveHeadline,
  toRecord,
} from "@/components/intraday/notification-utils"
import type { KafkaNotification } from "@/components/intraday/types"
import { NotificationBody } from "@/components/intraday/parts/NotificationBody"
import { NotificationActions } from "@/components/intraday/parts/NotificationActions"
import { X } from "lucide-react"

function resolveBody(notification: KafkaNotification): string {
  if (typeof notification.body === "string" && notification.body.trim().length) {
    return notification.body
  }

  const record = toRecord(notification.data)
  if (record) {
    if (typeof record.message === "string" && record.message.trim().length) {
      return record.message
    }
    if (typeof record.summary === "string" && record.summary.trim().length) {
      return record.summary
    }
    if (typeof record.description === "string" && record.description.trim().length) {
      return record.description
    }
    if (typeof record.note === "string" && record.note.trim().length) {
      return record.note
    }
  }

  return "Live intraday signal received. Review and act promptly."
}

function resolveTimestamp(notification: KafkaNotification): string {
  return (
    formatTemporal(notification.timestamp) ??
    notification.timestamp ??
    new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date())
  )
}

function useIntradayNotifications(): {
  notifications: KafkaNotification[]
  statusMessage: string | null
} {
  const {
    notifications: rawNotifications,
    status,
    error,
  } = useNotificationStream({
    maxItems: 20,
  })

  const notifications = useMemo(() => {
    return rawNotifications
      .map((item) => coerceNotification(item))
      .filter((item): item is KafkaNotification => Boolean(item))
  }, [rawNotifications])

  const statusMessage = useMemo(() => {
    if (error) {
      return error
    }
    if (status === "connecting") {
      return "Connecting to intraday notification stream..."
    }
    if (status === "open" && notifications.length === 0) {
      return "Listening for live intraday signals."
    }
    if (status === "error") {
      return "Attempting to reconnect to the notification stream."
    }
    return null
  }, [error, status, notifications.length])

  return { notifications, statusMessage }
}

export function IntradayNotifications() {
  const { notifications, statusMessage } = useIntradayNotifications()
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set())

  const handleDismiss = useCallback((id: string) => {
    setDismissedIds((prev) => {
      const next = new Set(prev)
      next.add(id)
      return next
    })
  }, [])

  const enrichedNotifications = useMemo(() => {
    return notifications
      .filter((notification) => !dismissedIds.has(notification.id))
      .map((notification) => ({
        notification,
        title: resolveHeadline(notification),
        body: resolveBody(notification),
        timestamp: resolveTimestamp(notification),
      }))
  }, [notifications, dismissedIds])

  return (
    <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader className="gap-1">
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Intraday alerts in real time
        </CardDescription>
        <CardTitle className="h-title text-xl text-[#fafafa]">Notifications</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto">
        {statusMessage ? (
          <div className="mb-4 rounded-xl border border-white/10 bg-black/25 px-4 py-3 text-sm text-white/60">
            {statusMessage}
          </div>
        ) : null}

        {enrichedNotifications.length === 0 ? (
          <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/20 text-sm text-white/50">
            Waiting for the next intraday trigger.
          </div>
        ) : (
          <div className="space-y-3 pr-2">
            <AnimatePresence initial={false} mode="popLayout">
              {enrichedNotifications.map(({ notification, title, body, timestamp }) => (
                <motion.div
                  key={notification.id}
                  layout
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  transition={{ duration: 0.45, ease: [0.21, 0.61, 0.35, 1] }}
                  className="group relative rounded-xl border border-white/10 bg-black/30 p-4 shadow-[0_8px_24px_-8px_rgba(0,0,0,0.6)] backdrop-blur-sm"
                >
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <span className="text-xs font-medium uppercase tracking-wide text-white/45">
                      {timestamp}
                    </span>
                    <span className="rounded-md bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white/50">
                      Alert
                    </span>
                    <button
                      type="button"
                      onClick={() => handleDismiss(notification.id)}
                      className="rounded-full border border-white/10 bg-white/5 p-1 text-white/60 transition hover:border-white/20 hover:bg-white/15 hover:text-white"
                      aria-label="Dismiss notification"
                    >
                      <X className="size-3.5" />
                    </button>
                  </div>
                  <h3 className="mb-1.5 text-base font-semibold text-[#fafafa]">{title}</h3>
                  <p className="text-sm leading-relaxed text-white/70">{body}</p>

                  <NotificationBody notification={notification} />
                  <NotificationActions actions={notification.actions} />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

