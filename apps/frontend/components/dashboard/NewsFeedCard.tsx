import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"

import type { NewsItem } from "@/lib/dashboardTypes"

type NewsFeedCardProps = {
  news: NewsItem | null
}

export function NewsFeedCard({ news }: NewsFeedCardProps) {
  if (!news) {
    return null
  }

  return (
    <Card className="card-glass neon-hover rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader className="gap-1">
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Live News Feed
        </CardDescription>
        <CardTitle className="h-title text-xl text-[#fafafa]">{news.headline}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm text-white/70">
        <p className="leading-relaxed text-white/70">{news.summary}</p>
      </CardContent>
      <CardFooter className="flex flex-col items-start gap-1 text-xs text-white/45">
        <span className="uppercase tracking-wide">{news.publisher}</span>
        <span>{news.timestamp}</span>
      </CardFooter>
    </Card>
  )
}

