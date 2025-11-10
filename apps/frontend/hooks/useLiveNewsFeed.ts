import { useMemo } from "react"

import type { NewsItem } from "@/lib/dashboardTypes"
import type { NotificationStreamItem } from "@/lib/notificationStreamTypes"

import { useNotificationStream } from "./useNotificationStream"

type UseLiveNewsFeedResult = {
  news: NewsItem[]
  statusMessage: string | null
}

const MAX_ITEMS = 30
const ALLOWED_TYPES = new Set([
  "news-stock-recommendation",
  "news-sentiment-article",
  "news-sector-analysis",
])

function normalizeTimestamp(timestamp?: string): string {
  if (!timestamp) {
    return new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date())
  }

  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) {
    return timestamp
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed)
}

function toNewsItem(notification: NotificationStreamItem): NewsItem | null {
  const id = notification.id
  if (!id) {
    return null
  }

  const data = notification.data ?? {}
  const headline =
    notification.title ||
    (typeof data.title === "string" && data.title.trim().length > 0 ? data.title : undefined) ||
    (typeof data.stockName === "string" && data.stockName.trim().length > 0 ? data.stockName : undefined) ||
    (typeof data.stream === "string" && data.stream.trim().length > 0 ? data.stream : undefined) ||
    "Live Market Intelligence"

  const publisher = "AgentInvest"

  const summaryCandidates = [
    notification.body,
    typeof data.summary === "string" ? data.summary : undefined,
    typeof data.content === "string" ? data.content : undefined,
    typeof data.detailedAnalysis === "string" ? data.detailedAnalysis : undefined,
    typeof data.tradeSignal === "string" ? `Signal: ${data.tradeSignal}` : undefined,
  ]

  const summaryBase = summaryCandidates.find((candidate) => typeof candidate === "string" && candidate.trim().length > 0)

  const summary = summaryBase ? truncate(summaryBase, 320) : "Live feed update incoming."

  return {
    id,
    headline,
    publisher,
    timestamp: normalizeTimestamp(notification.timestamp),
    summary,
  }
}

function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value
  }
  return `${value.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`
}

export function useLiveNewsFeed(): UseLiveNewsFeedResult {
  const { notifications, status, error } = useNotificationStream({ maxItems: MAX_ITEMS })

  const news = useMemo(() => {
    return notifications
      .filter((notification) => {
        if (!notification.type) {
          return false
        }
        return ALLOWED_TYPES.has(notification.type)
      })
      .map((notification) => toNewsItem(notification))
      .filter((item): item is NewsItem => Boolean(item))
  }, [notifications])

  const statusMessage = useMemo(() => {
    if (error) {
      return error
    }
    if (status === "connecting") {
      return "Fetching the latest headlines for you…"
    }
    if (status === "open" && news.length === 0) {
      return "Fetching the latest headlines for you…"
    }
    if (status === "error") {
      return "Attempting to reconnect to the live news stream."
    }
    return null
  }, [error, status, news.length])

  return { news, statusMessage }
}


