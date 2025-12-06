import { type ReactNode } from "react"

import { Activity, AlertTriangle, BarChart3, Newspaper, PieChart, Sparkles, X } from "lucide-react"

import { cn } from "@/lib/utils"
import { normalizeNumber, toRecord } from "../notification-utils"

import type { KafkaNotification } from "../types"

import { NotificationActions } from "./NotificationActions"
import { NotificationBody } from "./NotificationBody"
import { NotificationHeader } from "./NotificationHeader"

const notificationTopicTitles: Record<string, string> = {
  "nse-signal": "Trading Signal",
  "news-stock-recommendation": "Stock Recommendation",
  "news-sentiment-article": "Sentiment Analysis",
  "news-sector-analysis": "Sector Analysis",
  "portfolio-risk-alert": "Risk Alert",
  generic: "Live Notification",
}

const topicStyles: Record<
  string,
  {
    accent: string
    icon: string
    badge: string
  }
> = {
  "nse-signal": {
    accent: "before:bg-[radial-gradient(circle_at_top,_rgba(16,185,129,0.28),transparent_55%)]",
    icon: "border-emerald-400/30 bg-emerald-500/15 text-emerald-200 shadow-[0_8px_24px_-14px_rgba(16,185,129,0.65)]",
    badge:
      "text-emerald-300",
  },
  "news-stock-recommendation": {
    accent: "before:bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.28),transparent_55%)]",
    icon: "border-sky-400/30 bg-sky-500/15 text-sky-200 shadow-[0_8px_24px_-14px_rgba(56,189,248,0.65)]",
    badge:
      "text-sky-300",
  },
  "news-sentiment-article": {
    accent: "before:bg-[radial-gradient(circle_at_top,_rgba(129,140,248,0.3),transparent_55%)]",
    icon: "border-indigo-400/30 bg-indigo-500/18 text-indigo-200 shadow-[0_8px_24px_-14px_rgba(129,140,248,0.65)]",
    badge:
      "text-indigo-300",
  },
  "news-sector-analysis": {
    accent: "before:bg-[radial-gradient(circle_at_top,_rgba(250,204,21,0.26),transparent_55%)]",
    icon: "border-amber-400/30 bg-amber-500/14 text-amber-200 shadow-[0_8px_24px_-14px_rgba(250,204,21,0.55)]",
    badge:
      "text-amber-200",
  },
  "portfolio-risk-alert": {
    accent: "before:bg-[radial-gradient(circle_at_top,_rgba(248,113,113,0.28),transparent_55%)]",
    icon: "border-red-400/30 bg-red-500/15 text-red-200 shadow-[0_8px_24px_-14px_rgba(248,113,113,0.65)]",
    badge:
      "text-red-300",
  },
  generic: {
    accent: "before:bg-[radial-gradient(circle_at_top,_rgba(148,163,184,0.22),transparent_55%)]",
    icon: "border-white/15 bg-white/10 text-white/70 shadow-[0_8px_24px_-14px_rgba(148,163,184,0.45)]",
    badge:
      "text-white/65",
  },
}

const topicIcons: Record<string, ReactNode> = {
  "nse-signal": <Activity className="size-3.5" />,
  "news-stock-recommendation": <BarChart3 className="size-3.5" />,
  "news-sentiment-article": <Newspaper className="size-3.5" />,
  "news-sector-analysis": <PieChart className="size-3.5" />,
  "portfolio-risk-alert": <AlertTriangle className="size-3.5" />,
  generic: <Sparkles className="size-3.5" />,
}

export function NotificationItemCard({
  notification,
  onDismiss,
}: {
  notification: KafkaNotification
  onDismiss?: (id: string) => void
}) {
  const styles = topicStyles[notification.type] ?? topicStyles.generic
  const title = notificationTopicTitles[notification.type] ?? notificationTopicTitles.generic
  const icon = topicIcons[notification.type] ?? topicIcons.generic

  // Determine background color based on signal strength for nse-signal type
  const data = toRecord(notification.data)
  const signal = notification.type === "nse-signal" ? normalizeNumber(data?.signal) : null
  const bgColorClass =
    signal === 1
      ? "bg-emerald-950/40 border-emerald-500/30"
      : signal === 0
        ? "bg-amber-950/40 border-amber-500/30"
        : signal != null && signal !== 1 && signal !== 0
          ? "bg-red-950/40 border-red-500/30"
          : "bg-black/30 border-white/12"

  // Determine icon and badge colors based on signal
  const iconWrapperClass =
    signal === 1
      ? "border-emerald-400/40 bg-emerald-500/20 text-emerald-200 shadow-[0_8px_24px_-14px_rgba(16,185,129,0.65)]"
      : signal === 0
        ? "border-amber-400/40 bg-amber-500/20 text-amber-200 shadow-[0_8px_24px_-14px_rgba(250,204,21,0.65)]"
        : signal != null && signal !== 1 && signal !== 0
          ? "border-red-400/40 bg-red-500/20 text-red-200 shadow-[0_8px_24px_-14px_rgba(248,113,113,0.65)]"
          : styles.icon

  const badgeClass =
    signal === 1
      ? "text-emerald-300"
      : signal === 0
        ? "text-amber-300"
        : signal != null && signal !== 1 && signal !== 0
          ? "text-red-300"
          : styles.badge

  return (
    <article
      className={cn(
        "group relative overflow-hidden rounded-2xl border p-5 shadow-[0_18px_40px_-26px_rgba(0,0,0,0.85)] backdrop-blur-sm transition-transform duration-20",
        "before:absolute before:inset-0 before:-z-10 before:opacity-0 before:transition-opacity before:duration-300 group-hover:before:opacity-100",
        bgColorClass,
        // Only apply accent gradient if not using signal-based background
        signal == null && styles.accent,
      )}
    >
      {onDismiss && (
        <button
          type="button"
          onClick={() => onDismiss(notification.id)}
          className="absolute right-4 top-4 z-10 rounded-full border border-white/10 bg-white/5 p-1.5 text-white/60 transition hover:border-white/20 hover:bg-white/15 hover:text-white"
          aria-label="Dismiss notification"
        >
          <X className="size-3.5" />
        </button>
      )}
      <div className="pr-8">
        <NotificationHeader
          notification={notification}
          icon={icon}
          title={title}
          iconWrapperClass={iconWrapperClass}
          badgeClass={badgeClass}
        />
        <NotificationBody notification={notification} />
        <NotificationActions
          actions={notification.actions}
          signal={signal}
          notification={notification}
        />
      </div>
    </article>
  )
}

