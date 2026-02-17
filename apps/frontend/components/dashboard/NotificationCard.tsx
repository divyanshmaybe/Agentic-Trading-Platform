import { AnimatePresence, motion } from "framer-motion"
import { X } from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import type { Notification } from "@/lib/types/notifications"

type NotificationCardProps = {
  notifications: Notification[]
  title?: string
  description?: string
  onDismiss?: (id: string) => void
}

/**
 * Format Date to timestamp string for display
 */
function formatTimestamp(date: Date): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date)
}

export function NotificationCard({ 
  notifications, 
  title = "Live Notifications",
  description = "Keep up with your AI",
  onDismiss
}: NotificationCardProps) {
  const hasNotifications = notifications && notifications.length > 0

  // Determine empty state message based on title
  const emptyStateMessage = title === "Top Headlines" 
    ? "No headlines right now."
    : "No live notifications right now."

  return (
    <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader className="gap-1">
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          {description}
        </CardDescription>
        <CardTitle className="h-title text-xl text-[#fafafa]">{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto">
        {hasNotifications ? (
          <div className="space-y-3 pr-2">
            <AnimatePresence initial={false} mode="popLayout">
              {notifications.map((notification) => (
                <motion.div
                  key={notification.id}
                  layout
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  transition={{ duration: 0.45, ease: [0.21, 0.61, 0.35, 1] }}
                  className="group relative rounded-xl border border-white/1 p-4 pt-6 pr-10 shadow-[0_8px_24px_-8px_rgba(0,0,0,0.6)] backdrop-blur-sm"
                >
                  {onDismiss && (
                    <div className="absolute top-3 right-3 z-20">
                      <button
                        onClick={() => onDismiss(notification.id)}
                        className="p-1.5 rounded-full bg-black/30 hover:bg-black/50 transition flex items-center justify-center backdrop-blur-sm"
                        aria-label="Dismiss notification"
                      >
                        <X className="h-3.5 w-3.5 text-white/70 hover:text-white" strokeWidth={2} />
                      </button>
                    </div>
                  )}
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <span className="text-xs font-medium uppercase tracking-wide text-white/45">
                      {formatTimestamp(notification.createdAt)}
                    </span>
                    <div className="flex items-center gap-2">
                      {notification.symbol && (
                        <span className="rounded-md bg-blue-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-blue-300">
                          {notification.symbol}
                        </span>
                      )}
                      {notification.signal && (
                        <span className={`rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                          notification.signal.toLowerCase() === "buy"
                            ? "bg-emerald-500/20 text-emerald-300"
                            : notification.signal.toLowerCase() === "sell"
                            ? "bg-red-500/20 text-red-300"
                            : "bg-white/10 text-white/50"
                        }`}>
                          {notification.signal}
                        </span>
                      )}
                      {!notification.symbol && !notification.signal && (
                        <span className="rounded-md bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white/50">
                          Alert
                        </span>
                      )}
                    </div>
                  </div>
                  <h3 className="mb-1.5 text-base font-semibold text-[#fafafa]">
                    {notification.title || notification.category.replace(/_/g, " ")}
                  </h3>
                  <p className="text-sm leading-relaxed text-white/70">
                    {notification.summary ?? notification.title ?? "No details available"}
                  </p>
                  {notification.sentiment && (
                    <div className="mt-2 text-xs text-white/50">
                      Sentiment: <span className="font-medium text-white/70">{notification.sentiment}</span>
                    </div>
                  )}
                  {notification.confidence !== null && notification.confidence !== undefined && (
                    <div className="mt-1 text-xs text-white/50">
                      Confidence: <span className="font-medium text-white/70">{(notification.confidence * 100).toFixed(0)}%</span>
                    </div>
                  )}
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-sm text-neutral-500">
              {emptyStateMessage}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
