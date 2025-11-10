import { useCallback, useMemo, useState } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { X } from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import type { NewsItem } from "@/lib/dashboardTypes"

type NewsFeedCardProps = {
  news: NewsItem[]
  statusMessage?: string | null
}

export function NewsFeedCard({ news, statusMessage }: NewsFeedCardProps) {
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set())

  const handleDismiss = useCallback((id: string) => {
    setDismissedIds((prev) => {
      const next = new Set(prev)
      next.add(id)
      return next
    })
  }, [])

  const visibleNews = useMemo(() => {
    if (!news?.length) {
      return []
    }
    return news.filter((item) => !dismissedIds.has(item.id))
  }, [news, dismissedIds])

  const hasNews = visibleNews.length > 0

  return (
    <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader className="gap-1">
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Live Macro Feed
        </CardDescription>
        <CardTitle className="h-title text-xl text-[#fafafa]">Top Headlines</CardTitle>
      </CardHeader>
      <CardContent className={hasNews ? "flex-1 overflow-y-auto" : "flex flex-1 items-center justify-center"}>
        {hasNews && statusMessage ? (
          <div className="mb-4 rounded-xl border border-white/10 bg-black/25 px-4 py-3 text-sm text-white/60">
            {statusMessage}
          </div>
        ) : null}

        {hasNews ? (
          <div className="space-y-3 pr-2">
            <AnimatePresence initial={false} mode="popLayout">
              {visibleNews.map((item) => (
                <motion.article
                  key={item.id}
                  layout
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  transition={{ duration: 0.45, ease: [0.21, 0.61, 0.35, 1] }}
                  className="rounded-xl border border-white/10 bg-black/30 p-4 shadow-[0_8px_24px_-8px_rgba(0,0,0,0.6)] backdrop-blur-sm"
                >
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <span className="rounded-md bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white/50">
                        {item.publisher}
                      </span>
                      <span className="text-xs font-medium uppercase tracking-wide text-white/45">{item.timestamp}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDismiss(item.id)}
                      className="rounded-full border border-white/10 bg-white/5 p-1 text-white/60 transition hover:border-white/20 hover:bg-white/15 hover:text-white"
                      aria-label="Dismiss headline"
                    >
                      <X className="size-3.5" />
                    </button>
                  </div>
                  <h3 className="mb-2 text-lg font-semibold leading-tight text-[#fafafa]">{item.headline}</h3>
                  <p className="text-sm leading-relaxed text-white/70">{item.summary}</p>
                </motion.article>
              ))}
            </AnimatePresence>
          </div>
        ) : (
          <div className="text-center text-sm text-white/50">
            {statusMessage ?? "Fetching the latest headlines for you…"}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
