/**
 * NotificationDTO - Canonical type for notification data from Redis PubSub and REST API
 * This matches the structure published by NotificationPublisher in the backend
 */
export interface NotificationDTO {
  id: string;
  kafkaKey: string | null;
  topic: string;
  category: string;
  title: string | null;
  summary: string | null;
  symbol: string | null;
  sector: string | null;
  sentiment: string | null;
  signal: string | null;
  confidence: number | null;
  url: string | null;
  rawPayload: any;
  createdAt: string; // ISO string
  eventTime: string | null; // ISO string or null
}

/**
 * Notification - Internal type for UI components with Date objects
 * Converted from NotificationDTO in hooks for easier date handling
 */
export interface Notification {
  id: string;
  kafkaKey: string | null;
  topic: string;
  category: string;
  title: string | null;
  summary: string | null;
  symbol: string | null;
  sector: string | null;
  sentiment: string | null;
  signal: string | null;
  confidence: number | null;
  url: string | null;
  rawPayload: any;
  createdAt: Date;
  eventTime: Date | null;
}

/**
 * Convert NotificationDTO to Notification (ISO strings -> Date objects)
 */
export function dtoToNotification(dto: NotificationDTO): Notification {
  return {
    ...dto,
    createdAt: new Date(dto.createdAt),
    eventTime: dto.eventTime ? new Date(dto.eventTime) : null,
  };
}

/**
 * Convert Notification to NotificationDTO (Date objects -> ISO strings)
 */
export function notificationToDto(notification: Notification): NotificationDTO {
  return {
    ...notification,
    createdAt: notification.createdAt.toISOString(),
    eventTime: notification.eventTime ? notification.eventTime.toISOString() : null,
  };
}

