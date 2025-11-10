import { Fragment, type ReactNode } from "react"

import {
  deriveSignalLabel,
  formatTemporal,
  normalizeCurrency,
  normalizeNumber,
  normalizePercent,
  toRecord,
} from "../notification-utils"
import type { KafkaNotification } from "../types"

import { DetailRow } from "./DetailRow"

type NotificationRenderer = (notification: KafkaNotification) => ReactNode

export function NotificationBody({ notification }: { notification: KafkaNotification }) {
  const renderer = notificationRenderers[notification.type] ?? renderGenericNotification

  if (!notification.data && !notification.body) {
    return null
  }

  return <div className="mt-4 space-y-3 text-sm leading-relaxed text-white/80">{renderer(notification)}</div>
}

const notificationRenderers: Record<string, NotificationRenderer> = {
  "nse-signal": (notification) => {
    const data = toRecord(notification.data)
    if (!data) return null

    const signal = normalizeNumber(data.signal)
    const signalLabel = deriveSignalLabel(signal)
    const confidence = normalizePercent(data.confidence)

    return (
      <NotificationBodySection>
        {renderIfPresent(data.explanation)}
        <DetailRow label="Signal Strength" value={signal != null ? signal.toFixed(2) : "N/A"} />
        <DetailRow label="Positioning" value={signalLabel ?? "Not provided"} />
        <DetailRow label="Confidence" value={confidence ?? "Not provided"} />
        <DetailRow label="Filing Time" value={formatTemporal(data.filingTime)} />
      </NotificationBodySection>
    )
  },
  "news-stock-recommendation": (notification) => {
    const data = toRecord(notification.data)
    if (!data) return null

    return (
      <NotificationBodySection>
        {renderIfPresent(data.detailedAnalysis)}
        <DetailRow label="Trade Signal" value={String(data.tradeSignal ?? "N/A")} />
        <DetailRow label="Sector" value={String(data.sector ?? "N/A")} />
        <DetailRow label="Window" value={String(data.timeWindowInvestment ?? "N/A")} />
      </NotificationBodySection>
    )
  },
  "news-sentiment-article": (notification) => {
    const data = toRecord(notification.data)
    if (!data) return null

    const sentiment = String(data.sentiment ?? "").toUpperCase()

    return (
      <NotificationBodySection>
        {renderIfPresent(data.content)}
        <DetailRow label="Sentiment" value={sentiment || "N/A"} />
      </NotificationBodySection>
    )
  },
  "news-sector-analysis": (notification) => {
    const data = toRecord(notification.data)
    if (!data) return null

    return (
      <NotificationBodySection>
        {renderIfPresent(data.analysis, true)}
      </NotificationBodySection>
    )
  },
  "portfolio-risk-alert": (notification) => {
    const data = toRecord(notification.data)
    if (!data) return null

    const fallPercent = normalizePercent(data.fallPercent)
    const currentChange = normalizePercent(data.currentChange)
    const currentPrice = normalizeCurrency(data.currentPrice)

    return (
      <NotificationBodySection>
        {renderIfPresent(data.alert)}
        <DetailRow label="Drawdown" value={fallPercent ?? "N/A"} />
        <DetailRow label="Daily Change" value={currentChange ?? "N/A"} />
        <DetailRow label="Price" value={currentPrice ?? "N/A"} />
        <DetailRow label="Source" value={String(data.source ?? "risk_agent_pipeline")} />
      </NotificationBodySection>
    )
  },
}

function renderGenericNotification(notification: KafkaNotification) {
  if (!notification.data && !notification.body) {
    return null
  }

  const data = toRecord(notification.data)
  if (data) {
    return (
      <NotificationBodySection>
        {renderIfPresent(data.summary)}
        <DetailRow label="Source" value={notification.topic ?? "Unknown"} />
      </NotificationBodySection>
    )
  }

  if (notification.body) {
    return <NotificationBodySection>{renderIfPresent(notification.body)}</NotificationBodySection>
  }

  return <NotificationBodySection>{renderIfPresent(notification.data)}</NotificationBodySection>
}

function NotificationBodySection({ children }: { children: ReactNode }) {
  return <Fragment>{children}</Fragment>
}

function renderIfPresent(value: unknown, preserveWhitespace = false) {
  if (!value) {
    return null
  }

  const className = preserveWhitespace ? "whitespace-pre-line" : undefined
  return <p className={className}>{String(value)}</p>
}

