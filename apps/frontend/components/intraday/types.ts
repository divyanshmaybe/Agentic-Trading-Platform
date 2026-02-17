/**
 * @deprecated These types are for legacy Kafka notification compatibility.
 * New notification system uses NotificationDTO/Notification types from @/lib/types/notifications.
 * These types are kept for backwards compatibility with NotificationItemCard and other legacy components.
 */
export type {
  NotificationStreamAction as KafkaNotificationAction,
  NotificationStreamItem as KafkaNotification,
} from "@/lib/notificationStreamTypes"
