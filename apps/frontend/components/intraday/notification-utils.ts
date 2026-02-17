/**
 * @deprecated This file contains legacy Kafka notification utilities.
 * New notification system uses NotificationDTO/Notification types from @/lib/types/notifications.
 * These utilities are kept for backwards compatibility with NotificationItemCard and other legacy components.
 */
import type { KafkaNotification, KafkaNotificationAction } from "./types"

export function coerceNotification(input: unknown): KafkaNotification | null {
  if (!isRecord(input)) {
    return null
  }

  const id = typeof input.id === "string" ? input.id : undefined
  if (!id) {
    return null
  }

  return {
    id,
    type: typeof input.type === "string" ? input.type : "generic",
    topic: typeof input.topic === "string" ? input.topic : undefined,
    timestamp: typeof input.timestamp === "string" ? input.timestamp : undefined,
    title: typeof input.title === "string" ? input.title : undefined,
    body: typeof input.body === "string" ? input.body : undefined,
    data: isRecord(input.data) ? input.data : undefined,
    actions: coerceActions(input.actions),
  }
}

export function resolveIntroMessage({
  status,
  error,
  notifications,
}: {
  status: string
  error: string | null
  notifications: KafkaNotification[]
}) {
  if (error) {
    return error
  }
  if (status === "connecting") {
    return "Connecting to live notification stream..."
  }
  if (status === "open" && !notifications.length) {
    return "Listening for live signals from all high-risk pipelines."
  }
  if (status === "error") {
    return "Attempting to reconnect to the notification stream."
  }
  return null
}

export function resolveHeadline(notification: KafkaNotification): string {
  const { data, type } = notification

  if (type === "nse-signal" && isRecord(data) && "symbol" in data) {
    return (data.symbol as string) ?? "NSE Signal"
  }
  if (type === "news-stock-recommendation" && isRecord(data) && "stock_name" in data) {
    return ((data.stock_name as string) || (data.sector as string)) ?? "Recommendation Insight"
  }
  if (type === "news-sentiment-article" && isRecord(data) && "title" in data) {
    return ((data.title as string) || (data.stream as string)) ?? "Sentiment Pulse"
  }
  if (type === "news-sector-analysis" && isRecord(data) && "analysis" in data) {
    return "Sector Overview"
  }
  if (type === "portfolio-risk-alert" && isRecord(data) && "ticker" in data) {
    return ((data.ticker as string) || (data.name as string)) ?? "Risk Alert"
  }

  if (isRecord(data) && "title" in data && typeof data.title === "string") {
    return data.title
  }
  if (notification.title) {
    return notification.title
  }

  return notification.topic ?? "Notification"
}

export function normalizeNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value
  }
  if (typeof value === "string") {
    const numeric = Number(value)
    if (!Number.isNaN(numeric) && Number.isFinite(numeric)) {
      return numeric
    }
  }
  return null
}

export function normalizePercent(value: unknown): string | null {
  const numeric = normalizeNumber(value)
  if (numeric == null) {
    return null
  }
  const percent = Math.abs(numeric) <= 1 && Math.abs(numeric) > 0 ? numeric * 100 : numeric
  return `${percent.toFixed(1)}%`
}

export function normalizeCurrency(value: unknown): string | null {
  const numeric = normalizeNumber(value)
  if (numeric == null) {
    return null
  }
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(numeric)
}

export function formatTemporal(value: unknown): string | null {
  if (typeof value !== "string") {
    return null
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date)
}

export function deriveSignalLabel(signal: number | null) {
  if (signal == null) {
    return null
  }
  if (signal > 0) {
    return "Bullish"
  }
  if (signal < 0) {
    return "Bearish"
  }
  return "Neutral"
}

export function toRecord(value: unknown): Record<string, unknown> | null {
  return isRecord(value) ? value : null
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function coerceActions(input: unknown): KafkaNotificationAction[] | undefined {
  if (!Array.isArray(input)) {
    return undefined
  }

  const actions: KafkaNotificationAction[] = []

  for (const action of input) {
    if (!isRecord(action)) {
      continue
    }

    const label = typeof action.label === "string" ? action.label : undefined
    const value = typeof action.value === "string" ? action.value : undefined
    const href = typeof action.href === "string" ? action.href : undefined

    if (!label || !value) {
      continue
    }

    actions.push({ label, value, href })
  }

  return actions
}

