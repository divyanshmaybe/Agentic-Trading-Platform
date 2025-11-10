import { useEffect, useMemo, useRef, useState } from "react"

import type { NotificationItem } from "@/lib/dashboardTypes"

type ConnectionStatus = "connecting" | "open" | "closed" | "error"

type UseNotificationStreamOptions = {
  topics?: string[]
  maxItems?: number
}

type NotificationStreamState = {
  notifications: NotificationItem[]
  status: ConnectionStatus
  error: string | null
  activeTopics: string[]
  lastEventAt: number | null
}

const DEFAULT_MAX_ITEMS = 50

export function useNotificationStream(options: UseNotificationStreamOptions = {}): NotificationStreamState {
  const { topics = [], maxItems = DEFAULT_MAX_ITEMS } = options
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [status, setStatus] = useState<ConnectionStatus>("connecting")
  const [error, setError] = useState<string | null>(null)
  const [activeTopics, setActiveTopics] = useState<string[]>([])
  const [lastEventAt, setLastEventAt] = useState<number | null>(null)

  const eventSourceRef = useRef<EventSource | null>(null)
  const seenIdsRef = useRef<Set<string>>(new Set())

  const streamUrl = useMemo(() => {
    const params = new URLSearchParams()
    if (topics.length) {
      params.set("topics", topics.join(","))
    }
    const query = params.toString()
    return `/api/notifications/stream${query ? `?${query}` : ""}`
  }, [topics])

  useEffect(() => {
    setStatus("connecting")
    setError(null)

    const eventSource = new EventSource(streamUrl, { withCredentials: true })
    eventSourceRef.current = eventSource

    const handleOpen = () => {
      setStatus("open")
      setError(null)
    }

    const handleStatus = (event: MessageEvent<string>) => {
      setStatus("open")
      try {
        const data = JSON.parse(event.data) as { topics?: string[] }
        if (Array.isArray(data.topics)) {
          setActiveTopics(data.topics)
        }
      } catch (err) {
        console.warn("[Notifications] Failed to decode status event:", err)
      }
    }

    const handleNotification = (event: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(event.data) as NotificationItem
        if (payload?.id && seenIdsRef.current.has(payload.id)) {
          return
        }

        if (payload?.id) {
          seenIdsRef.current.add(payload.id)
        }

        setNotifications((prev) => {
          const next = [payload, ...prev]
          if (next.length > maxItems) {
            next.length = maxItems
          }
          return next
        })
        setLastEventAt(Date.now())
      } catch (err) {
        console.warn("[Notifications] Failed to parse notification event:", err, event.data)
      }
    }

    const handleError = (event: Event) => {
      setStatus("error")
      setError("Connection interrupted. Retrying...")
      console.warn("[Notifications] SSE error:", event)
    }

    const handlePing = () => {
      setLastEventAt(Date.now())
    }

    eventSource.addEventListener("open", handleOpen)
    eventSource.addEventListener("status", handleStatus)
    eventSource.addEventListener("notification", handleNotification)
    eventSource.addEventListener("error", handleError)
    eventSource.addEventListener("ping", handlePing)

    return () => {
      eventSource.removeEventListener("open", handleOpen)
      eventSource.removeEventListener("status", handleStatus)
      eventSource.removeEventListener("notification", handleNotification)
      eventSource.removeEventListener("error", handleError)
      eventSource.removeEventListener("ping", handlePing)
      eventSource.close()
      eventSourceRef.current = null
      setStatus("closed")
    }
  }, [streamUrl, maxItems])

  return {
    notifications,
    status,
    error,
    activeTopics,
    lastEventAt,
  }
}

