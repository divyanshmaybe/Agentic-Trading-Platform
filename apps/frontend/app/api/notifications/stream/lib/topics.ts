import { NextRequest } from "next/server"

const DEFAULT_TOPICS = [
  process.env.NSE_FILINGS_SIGNAL_TOPIC ?? "nse_filings_trading_signal",
  process.env.NEWS_STOCK_RECOMMENDATIONS_TOPIC ?? "news_pipeline_stock_recomendations",
  process.env.NEWS_SENTIMENT_ARTICLES_TOPIC ?? "news_pipeline_sentiment_articles",
  process.env.NEWS_SECTOR_ANALYSIS_TOPIC ?? "news_pipeline_sector_analysis",
  process.env.PORTFOLIO_RISK_ALERTS_TOPIC ?? process.env.RISK_ALERTS_TOPIC ?? undefined,
].filter((topic): topic is string => Boolean(topic))

export function resolveTopics(request: NextRequest): string[] {
  const topicsParam = request.nextUrl.searchParams.get("topics")
  const topics = topicsParam
    ? topicsParam.split(",").map((topic) => topic.trim()).filter(Boolean)
    : DEFAULT_TOPICS

  const uniqueTopics = Array.from(new Set(topics))
  if (!uniqueTopics.length) {
    throw new Error("No Kafka topics configured for notification streaming")
  }

  return uniqueTopics
}

export { DEFAULT_TOPICS }

