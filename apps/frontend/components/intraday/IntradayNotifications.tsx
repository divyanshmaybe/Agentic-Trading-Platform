"use client"

import { useMemo, useState, useCallback } from "react"
import { AnimatePresence, motion } from "framer-motion"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useNotificationStream } from "@/hooks/useNotificationStream"
import { coerceNotification } from "@/components/intraday/notification-utils"
import type { KafkaNotification } from "@/components/intraday/types"
import { NotificationItemCard } from "@/components/intraday/parts/NotificationItemCard"


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

  const visibleNotifications = useMemo(() => {
    return notifications.filter((notification) => !dismissedIds.has(notification.id))
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

        {visibleNotifications.length === 0 ? (
          <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/20 text-sm text-white/50">
            Waiting for the next intraday trigger.
          </div>
        ) : (
          <div className="space-y-4 pr-2">
            <AnimatePresence initial={false} mode="popLayout">
              {visibleNotifications.map((notification) => (
                <motion.div
                  key={notification.id}
                  layout
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  transition={{ duration: 0.45, ease: [0.21, 0.61, 0.35, 1] }}
                >
                  <NotificationItemCard notification={notification} onDismiss={handleDismiss} />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

