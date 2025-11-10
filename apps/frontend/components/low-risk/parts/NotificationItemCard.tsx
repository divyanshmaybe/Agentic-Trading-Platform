import { type ReactNode } from "react"

import { Activity, AlertTriangle, BarChart3, Newspaper, PieChart, Sparkles } from "lucide-react"

import { cn } from "@/lib/utils"

import type { KafkaNotification } from "../types"

import { NotificationActions } from "./NotificationActions"
import { NotificationBody } from "./NotificationBody"
import { NotificationHeader } from "./NotificationHeader"

const notificationTopicTitles: Record<string, string> = {
  "nse-signal": "NSE Filing Signal",
  "news-stock-recommendation": "News Stock Insight",
  "news-sentiment-article": "News Sentiment",
  "news-sector-analysis": "Sector Analysis",
  "portfolio-risk-alert": "Risk Alert",
  generic: "Live Notification",
}

const topicAccentClasses: Record<string, string> = {
  "nse-signal": "border-emerald-500/30 bg-emerald-600/[0.12]",
  "news-stock-recommendation": "border-sky-500/30 bg-sky-600/[0.14]",
  "news-sentiment-article": "border-indigo-500/30 bg-indigo-600/[0.12]",
  "news-sector-analysis": "border-amber-500/30 bg-amber-600/[0.1]",
  "portfolio-risk-alert": "border-red-500/30 bg-red-600/[0.12]",
  generic: "border-white/15 bg-white/12",
}

const topicIcons: Record<string, ReactNode> = {
  "nse-signal": <Activity className="size-3.5" />,
  "news-stock-recommendation": <BarChart3 className="size-3.5" />,
  "news-sentiment-article": <Newspaper className="size-3.5" />,
  "news-sector-analysis": <PieChart className="size-3.5" />,
  "portfolio-risk-alert": <AlertTriangle className="size-3.5" />,
  generic: <Sparkles className="size-3.5" />,
}

export function NotificationItemCard({ notification }: { notification: KafkaNotification }) {
  const accentClass = topicAccentClasses[notification.type] ?? topicAccentClasses.generic
  const title = notificationTopicTitles[notification.type] ?? notificationTopicTitles.generic
  const icon = topicIcons[notification.type] ?? topicIcons.generic

  return (
    <article
      className={cn(
        "group relative overflow-hidden rounded-xl border border-white/12 bg-black/25 p-5 shadow-[0_16px_45px_-28px_rgba(0,0,0,0.9)] backdrop-blur-sm transition-colors duration-300",
        accentClass,
      )}
    >
      <NotificationHeader notification={notification} icon={icon} title={title} />
      <NotificationBody notification={notification} />
      <NotificationActions actions={notification.actions} />
    </article>
  )
}

