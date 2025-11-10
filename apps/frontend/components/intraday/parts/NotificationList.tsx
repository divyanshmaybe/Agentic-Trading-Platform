import type { KafkaNotification } from "../types"

import { NotificationItemCard } from "./NotificationItemCard"

export function NotificationList({ notifications }: { notifications: KafkaNotification[] }) {
  return (
    <>
      {notifications.map((notification) => (
        <NotificationItemCard key={notification.id} notification={notification} />
      ))}
    </>
  )
}

