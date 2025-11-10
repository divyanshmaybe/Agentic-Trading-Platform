"use client"

import { useMemo } from "react"

import { Card, CardContent } from "@/components/ui/card"
import { useNotificationStream } from "@/hooks/useNotificationStream"

import { NotificationIntro } from "./parts/NotificationIntro"
import { NotificationList } from "./parts/NotificationList"
import { NotificationPanelHeader } from "./parts/NotificationPanelHeader"
import { coerceNotification, resolveIntroMessage } from "./notification-utils"
import type { KafkaNotification } from "./types"

export function LowRiskNotificationPanel() {
  const { notifications: rawNotifications, status, error, activeTopics } = useNotificationStream({
    maxItems: 25,
  })

  const notifications = useMemo(() => {
    return rawNotifications
      .map((notification) => coerceNotification(notification))
      .filter((notification): notification is KafkaNotification => Boolean(notification))
  }, [rawNotifications])

  const introMessage = useMemo(
    () => resolveIntroMessage({ status, error, notifications }),
    [status, error, notifications],
  )

  return (
    <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-[#0d0d0d]/70 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <NotificationPanelHeader activeTopics={activeTopics} />
      <CardContent className="flex-1 overflow-y-auto">
        <div className="space-y-3 pr-1">
          <NotificationIntro message={introMessage} />
          <NotificationList notifications={notifications} />
        </div>
      </CardContent>
    </Card>
  )
}
