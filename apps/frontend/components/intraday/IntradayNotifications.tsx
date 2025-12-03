"use client"

import { useMemo, useCallback } from "react"
import { AnimatePresence, motion } from "framer-motion"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useIntradayNotifications as useIntradayNotificationsHook } from "@/components/hooks/useIntradayNotifications"
import type { Notification } from "@/lib/types/notifications"
import type { KafkaNotification } from "@/components/intraday/types"
import { NotificationItemCard } from "@/components/intraday/parts/NotificationItemCard"

/**
 * Convert new Notification type to KafkaNotification format for NotificationItemCard
 * This is a temporary adapter until NotificationItemCard is updated
 */
function notificationToKafkaFormat(notification: Notification): KafkaNotification {
  // Map category to type
  // filing_signal is treated as nse-signal (trading signal) for proper UI rendering
  const categoryToType: Record<string, string> = {
    stock_recommendation: "news-stock-recommendation",
    news_sentiment: "news-sentiment-article",
    nse_signal: "nse-signal",
    filing_signal: "nse-signal", // Filing signals are trading signals
    portfolio_risk_alert: "portfolio-risk-alert",
    sector_analysis: "news-sector-analysis",
  }
  
  const type = categoryToType[notification.category] || "generic"
  
  // Format timestamp
  const timestamp = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(notification.createdAt)

  // Prepare data object with signal information for nse-signal type
  const data: Record<string, any> = {
    ...(notification.rawPayload || {}),
  }

  // Ensure signal value is available in data for nse-signal type
  if (type === "nse-signal" && notification.signal !== null && notification.signal !== undefined) {
    // Convert signal string to number if needed (signal can be "1", "-1", "0")
    const signalValue = typeof notification.signal === "string" 
      ? parseInt(notification.signal, 10) 
      : notification.signal
    if (!isNaN(signalValue)) {
      data.signal = signalValue
    }
  }

  // Include symbol if available
  if (notification.symbol) {
    data.symbol = notification.symbol
  }

  // Include confidence if available
  if (notification.confidence !== null && notification.confidence !== undefined) {
    data.confidence = notification.confidence
  }

  return {
    id: notification.id,
    type,
    topic: notification.topic,
    timestamp,
    title: notification.title || undefined,
    body: notification.summary || notification.title || undefined,
    data,
    actions: undefined, // Actions can be derived from signal if needed
  }
}

// Define notification type order and labels
// Note: Sentiment analysis (news-sentiment-article) is excluded from intraday page
const NOTIFICATION_TYPES = [
  { type: "news-stock-recommendation", label: "Stock Recommendations" },
	{ type: "nse-signal", label: "Trading Signals" },
  { type: "news-sector-analysis", label: "Sector Analysis" },
] as const

export function IntradayNotifications() {
  const { notifications, loading, dismiss } = useIntradayNotificationsHook()

  // Convert to KafkaNotification format for NotificationItemCard
  // Filter out sentiment analysis notifications (news_sentiment category)
  const kafkaNotifications = useMemo(() => {
    return notifications
      .filter((notification) => notification.category !== "news_sentiment")
      .map(notificationToKafkaFormat)
  }, [notifications])

  // Group notifications by type
  const notificationsByType = useMemo(() => {
    const grouped: Record<string, KafkaNotification[]> = {}
    
    // Initialize all types
    NOTIFICATION_TYPES.forEach(({ type }) => {
      grouped[type] = []
    })
    
    // Group notifications
    kafkaNotifications.forEach((notification) => {
      const type = notification.type || "generic"
      if (!grouped[type]) {
        grouped[type] = []
      }
      grouped[type].push(notification)
    })
    
    return grouped
  }, [kafkaNotifications])

  const handleDismiss = useCallback(
    async (id: string) => {
      try {
        await dismiss(id)
      } catch (error) {
        console.error("[Intraday Notifications] Failed to dismiss:", error)
      }
    },
    [dismiss]
  )

  const statusMessage = useMemo(() => {
    if (loading) {
      return "Loading notifications..."
    }
    if (notifications.length === 0) {
      return "Listening for live intraday signals."
    }
    return null
  }, [loading, notifications.length])

  // Show all notification types, even if empty
  const activeTypes = NOTIFICATION_TYPES

  return (
    <div className="w-full space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/45">
            Intraday alerts in real time
          </p>
          <h2 className="text-xl font-semibold text-[#fafafa]">Notifications</h2>
        </div>
      </div>

      {statusMessage ? (
        <div className="rounded-xl border border-white/10 bg-black/25 px-4 py-3 text-sm text-white/60">
          {statusMessage}
        </div>
      ) : null}

      {kafkaNotifications.length === 0 ? (
        <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/20 text-sm text-white/50">
          {loading ? "Loading notifications..." : "Waiting for the next intraday trigger."}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 xl:grid-cols-3">
          {activeTypes.map(({ type, label }) => {
            const typeNotifications = notificationsByType[type] || []
            
            return (
              <Card
                key={type}
                className="card-glass flex max-h-[80vh] w-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur"
              >
                <CardHeader className="shrink-0 gap-1 border-b border-white/10">
                  <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
                    {label}
                  </CardDescription>
                  <CardTitle className="text-sm font-medium text-[#fafafa]">
                    {typeNotifications.length} {typeNotifications.length === 1 ? "notification" : "notifications"}
                  </CardTitle>
                </CardHeader>
                <CardContent className="min-h-0 flex-1 overflow-y-auto">
                  {typeNotifications.length === 0 ? (
                    <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-white/10 bg-black/20 text-sm text-white/50">
                      No {label.toLowerCase()} yet
                    </div>
                  ) : (
                    <div className="space-y-4 pr-2 pt-4">
                      <AnimatePresence initial={false} mode="popLayout">
                        {typeNotifications.map((notification) => (
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
          })}
        </div>
      )}
    </div>
  )
}

