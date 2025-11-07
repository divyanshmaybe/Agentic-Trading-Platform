import { AnimatePresence, motion } from "framer-motion"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import type { NewsItem } from "@/lib/dashboardTypes"

type NewsFeedCardProps = {
  news: NewsItem[]
}

export function NewsFeedCard({ news }: NewsFeedCardProps) {
  if (!news || !news.length) {
    return null
  }

  return (
    <Card className="card-glass neon-hover flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader className="gap-1">
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Live Macro Feed
        </CardDescription>
        <CardTitle className="h-title text-xl text-[#fafafa]">Top Headlines</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto">
        <div className="space-y-3 pr-2">
          <AnimatePresence initial={false} mode="popLayout">
            {news.map((item) => (
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
                  <span className="rounded-md bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white/50">
                    {item.publisher}
                  </span>
                  <span className="text-xs font-medium uppercase tracking-wide text-white/45">{item.timestamp}</span>
                </div>
                <h3 className="mb-2 text-lg font-semibold leading-tight text-[#fafafa]">{item.headline}</h3>
                <p className="text-sm leading-relaxed text-white/70">{item.summary}</p>
              </motion.article>
            ))}
          </AnimatePresence>
        </div>
      </CardContent>
    </Card>
  )
}
