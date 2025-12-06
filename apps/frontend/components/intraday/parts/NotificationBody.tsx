import { Fragment, type ReactNode } from "react"
import { ExternalLink } from "lucide-react"

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

// Helper function to render text with clickable URLs
function renderTextWithLinks(text: string): ReactNode {
  if (!text) return null
  
  // Regex to match URLs
  const urlRegex = /(https?:\/\/[^\s)]+)/g
  const parts = text.split(urlRegex)
  
  return (
    <>
      {parts.map((part, idx) => {
        if (part.match(urlRegex)) {
          return (
            <a
              key={idx}
              href={part}
              target="_blank"
              rel="noreferrer noopener"
              className="text-blue-400 hover:text-blue-300 underline break-all"
            >
              {part}
            </a>
          )
        }
        return <span key={idx}>{part}</span>
      })}
    </>
  )
}

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

    // Style signal strength: green for 1 (bullish), yellow for 0 (neutral), red for others
    const signalStrengthValue = signal != null ? signal.toFixed(2) : "N/A"
    const signalStrengthClassName =
      signal === 1
        ? "text-emerald-400 font-bold"
        : signal === 0
          ? "text-amber-400 font-bold"
          : signal != null && signal !== 1 && signal !== 0
            ? "text-red-400 font-bold"
            : "text-white/80"

    // Extract new fields from rawPayload (available via data object)
    const attachmentUrlRaw = data.attachment_url || data.url
    const attachmentUrl = typeof attachmentUrlRaw === "string" ? attachmentUrlRaw : null
    const subjectOfAnnouncementRaw = data.subject_of_announcement
    const subjectOfAnnouncement =
      typeof subjectOfAnnouncementRaw === "string" ? subjectOfAnnouncementRaw : null
    const filingTime = data.filing_time || data.date_time_of_submission || data.generated_at

    // Determine link color based on signal: green for 1 (bullish), yellow for 0 (neutral), red for others
    const linkColorClassName =
      signal === 1
        ? "text-emerald-400 hover:text-emerald-300"
        : signal === 0
          ? "text-amber-400 hover:text-amber-300"
          : signal != null && signal !== 1 && signal !== 0
            ? "text-red-400 hover:text-red-300"
            : "text-emerald-400 hover:text-emerald-300"

    return (
      <NotificationBodySection>
        {renderIfPresent(data.explanation)}
        {subjectOfAnnouncement && (
          <DetailRow label="Subject" value={subjectOfAnnouncement} />
        )}
        <DetailRow
          label="Signal Strength"
          value={signalStrengthValue}
          valueClassName={signalStrengthClassName}
        />
        <DetailRow label="Positioning" value={signalLabel ?? "Not provided"} />
        <DetailRow label="Confidence" value={confidence ?? "Not provided"} />
        <DetailRow label="Filing Time" value={formatTemporal(filingTime)} />
        {attachmentUrl && (
          <DetailRow
            label="Attachment"
            value={
              <a
                href={attachmentUrl}
                target="_blank"
                rel="noreferrer"
                className={`${linkColorClassName} underline`}
              >
                View Filing
              </a>
            }
          />
        )}
      </NotificationBodySection>
    )
  },
  "news-stock-recommendation": (notification) => {
    const data = toRecord(notification.data)
    if (!data) return null

    const newsSource = typeof data.news_source === "string" ? data.news_source : null
    const detailedAnalysis = typeof data.detailed_analysis === "string" ? data.detailed_analysis : null

    return (
      <NotificationBodySection>
        <div className="space-y-3">
          {detailedAnalysis && (
            <p className="text-sm text-white/70 leading-relaxed">
              {renderTextWithLinks(detailedAnalysis)}
            </p>
          )}
          <DetailRow label="Trade Signal" value={String(data.trade_signal ?? "N/A")} />
          <DetailRow label="Sector" value={String(data.sector ?? "N/A")} />
          <DetailRow label="Window" value={String(data.time_window_investment ?? "N/A")} />
          {newsSource && (
            <DetailRow
              label="Source"
              value={
                <a
                  href={newsSource}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex items-center gap-1.5 text-blue-400 hover:text-blue-300 underline"
                >
                  View Article
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              }
            />
          )}
        </div>
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

    // Try to parse as JSON if it's a string
    let sectorData: Record<string, any> | null = null
    try {
      const analysisStr = String(data.analysis ?? "")
      if (analysisStr.trim().startsWith("{")) {
        sectorData = JSON.parse(analysisStr)
      }
    } catch (e) {
      // Not JSON, render as text
    }

    if (sectorData) {
      return (
        <div className="space-y-4">
          {Object.entries(sectorData).map(([sectorKey, sectorInfo]: [string, any]) => {
            if (!sectorInfo || typeof sectorInfo !== "object") return null
            
            const sector = String(sectorInfo.sector || sectorKey)
            const tradeSignal = String(sectorInfo.trade_signal_generated || sectorInfo.trade_signal || "Hold")
            const analysis = String(sectorInfo.analysis || "")
            
            // Determine signal color
            const signalColor = 
              tradeSignal.toLowerCase() === "buy" 
                ? "text-emerald-400" 
                : tradeSignal.toLowerCase() === "sell" 
                  ? "text-rose-400" 
                  : "text-amber-400"
            
            return (
              <div 
                key={sectorKey}
                className="rounded-lg border border-white/10 bg-white/5 p-4 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <h4 className="font-semibold text-[#fafafa]">{sector}</h4>
                  <span className={`text-xs font-semibold uppercase px-2 py-1 rounded ${signalColor}`}>
                    {tradeSignal}
                  </span>
                </div>
                {analysis && (
                  <p className="text-sm text-white/70 leading-relaxed">
                    {renderTextWithLinks(analysis)}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )
    }

    // Fallback to text rendering
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

