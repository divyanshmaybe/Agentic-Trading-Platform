"use client"

import { useMemo, type ReactNode } from "react"

import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Newspaper,
  PieChart,
  Sparkles,
} from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useNotificationStream } from "@/hooks/useNotificationStream"
import { cn } from "@/lib/utils"

type KafkaNotificationAction = {
  label: string
  value: string
  href?: string
}

type KafkaNotification = {
  id: string
  type: string
  topic?: string
  timestamp?: string
  data?: Record<string, unknown>
  actions?: KafkaNotificationAction[]
  title?: string
  body?: string
}

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

export function LowRiskNotificationPanel() {
  const { notifications: rawNotifications, status, error, activeTopics } = useNotificationStream({
    maxItems: 25,
  })

  const notifications = useMemo(() => {
    return rawNotifications
      .map((notification) => coerceNotification(notification))
      .filter((notification): notification is KafkaNotification => Boolean(notification))
  }, [rawNotifications])

  const introMessage = useMemo(() => {
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
  }, [status, notifications.length, error])

  return (
    <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-[#0d0d0d]/70 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader className="space-y-2 pb-5">
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Low-Risk Streams
        </CardDescription>
        <CardTitle className="h-title text-xl text-[#fafafa]">Live Portfolio Notifications</CardTitle>
        {activeTopics.length ? (
          <p className="text-[11px] text-white/50">
            Tracking:{" "}
            <span className="font-semibold text-white/70">
              {activeTopics.join(", ")}
            </span>
          </p>
        ) : null}
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto">
        <div className="space-y-3 pr-1">
          {introMessage ? (
            <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-sm text-white/70">
              {introMessage}
            </div>
          ) : null}
          {notifications.map((notification) => (
            <NotificationItemCard key={notification.id} notification={notification} />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function NotificationItemCard({ notification }: { notification: KafkaNotification }) {
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
      <header className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.3em] text-white/55">
            <span className="text-white/70">{icon}</span>
            <span>{title}</span>
          </div>
          <h3 className="mt-3 text-lg font-semibold text-[#fafafa]">
            {resolveHeadline(notification)}
          </h3>
        </div>
        <div className="text-right text-[11px] text-white/55">
          <div className="font-semibold uppercase tracking-[0.25em]">Topic</div>
          <div className="mt-1 max-w-[12ch] overflow-hidden text-ellipsis whitespace-nowrap font-mono text-white/70">
            {notification.topic ?? "live_stream"}
          </div>
          <div className="mt-2 font-semibold uppercase tracking-[0.25em] text-white/45">Time</div>
          <div className="mt-1 text-white/70">{notification.timestamp}</div>
        </div>
      </header>

      <div className="mt-4 space-y-3 text-sm leading-relaxed text-white/80">
        {renderBody(notification)}
      </div>

      {notification.actions?.length ? (
        <footer className="mt-4 flex flex-wrap gap-2">
          {notification.actions.map((action, index) => {
            const primary = index === 0
            const className = cn(
              "rounded-lg px-3 py-2 text-xs font-semibold uppercase tracking-[0.25em] transition-all duration-200",
              primary
                ? "border border-emerald-400/40 bg-emerald-500/15 text-emerald-200 hover:border-emerald-300/70 hover:bg-emerald-500/30"
                : "border border-white/15 bg-white/5 text-white/70 hover:bg-white/12 hover:text-white",
            )
            const key = `${action.value}-${index}`

            if (action.href || action.value.startsWith("http")) {
              const href = action.href ?? action.value
              return (
                <a key={key} href={href} target="_blank" rel="noreferrer" className={className}>
                  {action.label}
                </a>
              )
            }

            return (
              <button key={key} type="button" className={className} data-action={action.value}>
                {action.label}
              </button>
            )
          })}
        </footer>
      ) : null}
    </article>
  )
}

function resolveHeadline(notification: KafkaNotification): string {
  const { data, type } = notification

  if (type === "nse-signal" && data && "symbol" in data) {
    return (data.symbol as string) ?? "NSE Signal"
  }
  if (type === "news-stock-recommendation" && data && "stockName" in data) {
    return ((data.stockName as string) || (data.sector as string)) ?? "Recommendation Insight"
  }
  if (type === "news-sentiment-article" && data && "title" in data) {
    return ((data.title as string) || (data.stream as string)) ?? "Sentiment Pulse"
  }
  if (type === "news-sector-analysis" && data && "analysis" in data) {
    return "Sector Overview"
  }
  if (type === "portfolio-risk-alert" && data && "ticker" in data) {
    return ((data.ticker as string) || (data.name as string)) ?? "Risk Alert"
  }

  if (data && typeof data === "object" && "title" in data && typeof data.title === "string") {
    return data.title
  }
  if (notification.title) {
    return notification.title
  }

  return notification.topic ?? "Notification"
}

function renderBody(notification: KafkaNotification) {
  const { type, data } = notification

  switch (type) {
    case "nse-signal": {
      if (!data || typeof data !== "object") return null
      const signal = normalizeNumber((data as Record<string, unknown>).signal)
      let signalLabel: string | null = null
      if (signal != null) {
        if (signal > 0) {
          signalLabel = "Bullish"
        } else if (signal < 0) {
          signalLabel = "Bearish"
        } else {
          signalLabel = "Neutral"
        }
      }
      const confidence = normalizePercent((data as Record<string, unknown>).confidence)

      return (
        <>
          {"explanation" in data && data.explanation ? (
            <p>{String(data.explanation)}</p>
          ) : null}
          <DetailRow label="Signal Strength" value={signal != null ? signal.toFixed(2) : "N/A"} />
          <DetailRow label="Positioning" value={signalLabel ?? "Not provided"} />
          <DetailRow label="Confidence" value={confidence ?? "Not provided"} />
          <DetailRow label="Filing Time" value={formatTemporal((data as Record<string, unknown>).filingTime)} />
          <DetailRow label="Source" value={String((data as Record<string, unknown>).source ?? "nse_filings_pipeline")} />
        </>
      )
    }
    case "news-stock-recommendation": {
      if (!data || typeof data !== "object") return null
      return (
        <>
          {"detailedAnalysis" in data && data.detailedAnalysis ? (
            <p>{String(data.detailedAnalysis)}</p>
          ) : null}
          <DetailRow label="Trade Signal" value={String((data as Record<string, unknown>).tradeSignal ?? "N/A")} />
          <DetailRow label="Sector" value={String((data as Record<string, unknown>).sector ?? "N/A")} />
          <DetailRow label="Window" value={String((data as Record<string, unknown>).timeWindowInvestment ?? "N/A")} />
          <DetailRow label="Provider" value={String((data as Record<string, unknown>).provider ?? "N/A")} />
          <DetailRow label="Generated" value={formatTemporal((data as Record<string, unknown>).generatedAt)} />
        </>
      )
    }
    case "news-sentiment-article": {
      if (!data || typeof data !== "object") return null
      const sentiment = String((data as Record<string, unknown>).sentiment ?? "").toUpperCase()
      return (
        <>
          {"content" in data && data.content ? (
            <p>{String(data.content)}</p>
          ) : null}
          <DetailRow label="Stream" value={String((data as Record<string, unknown>).stream ?? "N/A")} />
          <DetailRow label="Sentiment" value={sentiment || "N/A"} />
          <DetailRow label="Provider" value={String((data as Record<string, unknown>).provider ?? "N/A")} />
          <DetailRow label="Generated" value={formatTemporal((data as Record<string, unknown>).generatedAt)} />
        </>
      )
    }
    case "news-sector-analysis": {
      if (!data || typeof data !== "object") return null
      return (
        <>
          {"analysis" in data && data.analysis ? (
            <p className="whitespace-pre-line">{String(data.analysis)}</p>
          ) : null}
          <DetailRow label="Streams" value={normalizeNumber((data as Record<string, unknown>).streamCount)?.toString() ?? "N/A"} />
          <DetailRow label="Provider" value={String((data as Record<string, unknown>).provider ?? "N/A")} />
          <DetailRow label="Generated" value={formatTemporal((data as Record<string, unknown>).generatedAt)} />
        </>
      )
    }
    case "portfolio-risk-alert": {
      if (!data || typeof data !== "object") return null
      const fallPercent = normalizePercent((data as Record<string, unknown>).fallPercent)
      const currentChange = normalizePercent((data as Record<string, unknown>).currentChange)
      const currentPrice = normalizeCurrency((data as Record<string, unknown>).currentPrice)

      return (
        <>
          {"alert" in data && data.alert ? (
            <p>{String(data.alert)}</p>
          ) : null}
          <DetailRow label="Drawdown" value={fallPercent ?? "N/A"} />
          <DetailRow label="Daily Change" value={currentChange ?? "N/A"} />
          <DetailRow label="Price" value={currentPrice ?? "N/A"} />
          <DetailRow label="Source" value={String((data as Record<string, unknown>).source ?? "risk_agent_pipeline")} />
          <DetailRow label="Generated" value={formatTemporal((data as Record<string, unknown>).generatedAt)} />
        </>
      )
    }
    default: {
      if (!data) {
        return null
      }

      if (typeof data === "object" && data) {
        return (
          <>
            {"summary" in data && data.summary ? (
              <p>{String(data.summary)}</p>
            ) : null}
            <DetailRow label="Source" value={notification.topic ?? "Unknown"} />
          </>
        )
      }

      if (notification.body) {
        return <p>{notification.body}</p>
      }

      return <p>{String(data)}</p>
    }
  }
}

function DetailRow({ label, value }: { label: string; value: string | null }) {
  if (!value) {
    return null
  }
  return (
    <div className="flex flex-wrap justify-between gap-2 text-xs uppercase tracking-[0.25em] text-white/60">
      <span>{label}</span>
      <span className="font-semibold text-white/80">{value}</span>
    </div>
  )
}

function normalizeNumber(value: unknown): number | null {
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

function normalizePercent(value: unknown): string | null {
  const numeric = normalizeNumber(value)
  if (numeric == null) {
    return null
  }
  const percent = Math.abs(numeric) <= 1 && Math.abs(numeric) > 0 ? numeric * 100 : numeric
  return `${percent.toFixed(1)}%`
}

function normalizeCurrency(value: unknown): string | null {
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

function formatTemporal(value: unknown): string | null {
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

function coerceNotification(input: unknown): KafkaNotification | null {
  if (!input || typeof input !== "object") {
    return null
  }

  const record = input as Record<string, unknown>
  const id = typeof record.id === "string" ? record.id : undefined
  if (!id) {
    return null
  }

  const type = typeof record.type === "string" ? record.type : "generic"
  const topic = typeof record.topic === "string" ? record.topic : undefined
  const timestamp = typeof record.timestamp === "string" ? record.timestamp : undefined
  const title = typeof record.title === "string" ? record.title : undefined
  const body = typeof record.body === "string" ? record.body : undefined
  const data =
    record.data && typeof record.data === "object" && !Array.isArray(record.data)
      ? (record.data as Record<string, unknown>)
      : undefined

  const actions = Array.isArray(record.actions)
    ? (record.actions
        .map((action): KafkaNotificationAction | null => {
          if (!action || typeof action !== "object") {
            return null
          }
          const actionRecord = action as Record<string, unknown>
          const label = typeof actionRecord.label === "string" ? actionRecord.label : undefined
          const value = typeof actionRecord.value === "string" ? actionRecord.value : undefined
          const href = typeof actionRecord.href === "string" ? actionRecord.href : undefined

          if (!label || !value) {
            return null
          }
          return { label, value, href }
        })
        .filter((action): action is KafkaNotificationAction => Boolean(action)) ?? undefined)
    : undefined

  return {
    id,
    type,
    topic,
    timestamp,
    data,
    actions,
    title,
    body,
  }
}

