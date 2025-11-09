"use client"

import { useMemo, useState } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { ChevronLeft, ChevronRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { alphaPagination, tradeHistory } from "@/mock/alphaData"

const rowVariants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.2 } },
  exit: { opacity: 0, y: -12, transition: { duration: 0.15 } },
}

const currencyFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
})

export function TradeTable() {
  const pageSize = alphaPagination.pageSize ?? 5
  const [page, setPage] = useState(0)

  const totalPages = Math.ceil(tradeHistory.length / pageSize)

  const pageItems = useMemo(
    () => tradeHistory.slice(page * pageSize, page * pageSize + pageSize),
    [page, pageSize],
  )

  const canPrev = page > 0
  const canNext = page < totalPages - 1

  const handlePrev = () => canPrev && setPage((prev) => prev - 1)
  const handleNext = () => canNext && setPage((prev) => prev + 1)

  return (
    <Card className="card-glass neon-hover rounded-2xl border border-white/10 bg-black/40 shadow-xl">
      <CardHeader>
        <CardTitle className="h-title text-xl text-white">Trade History</CardTitle>
      </CardHeader>
      <CardContent className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-white/10">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-white/60">
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Alpha Name</th>
                <th className="px-4 py-3">Entry Price</th>
                <th className="px-4 py-3">Exit Price</th>
                <th className="px-4 py-3">Profit/Loss</th>
                <th className="px-4 py-3 text-right">Trade Type</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10">
              <AnimatePresence initial={false}>
                {pageItems.map((trade) => {
                  const isProfit = trade.profitLossPct >= 0
                  return (
                    <motion.tr
                      key={trade.id}
                      variants={rowVariants}
                      initial="hidden"
                      animate="show"
                      exit="exit"
                      className="text-sm text-white/90"
                    >
                      <td className="px-4 py-3">{trade.time}</td>
                      <td className="px-4 py-3">{trade.alphaName}</td>
                      <td className="px-4 py-3 text-emerald-200">
                        {currencyFormatter.format(trade.entryPrice)}
                      </td>
                      <td className="px-4 py-3 text-emerald-200">
                        {currencyFormatter.format(trade.exitPrice)}
                      </td>
                      <td className={`px-4 py-3 font-semibold ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                        {isProfit ? "+" : ""}
                        {trade.profitLossPct.toFixed(2)}%
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span
                          className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                            trade.tradeType === "Long"
                              ? "bg-emerald-500/15 text-emerald-300"
                              : "bg-sky-500/15 text-sky-300"
                          }`}
                        >
                          {trade.tradeType}
                        </span>
                      </td>
                    </motion.tr>
                  )
                })}
              </AnimatePresence>
            </tbody>
          </table>
        </div>
      </CardContent>
      <CardFooter className="flex items-center justify-between border-t border-white/10 bg-black/30 px-6 py-4">
        <p className="text-xs text-white/60">
          Showing {page * pageSize + 1}-
          {Math.min(page * pageSize + pageSize, tradeHistory.length)} of {tradeHistory.length} trades
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={handlePrev}
            disabled={!canPrev}
            className="border border-white/10 bg-white/5 text-white hover:bg-white/10 disabled:opacity-40"
          >
            <ChevronLeft className="size-4" />
            <span className="sr-only">Previous page</span>
          </Button>
          <span className="text-xs text-white/70">
            Page {page + 1} / {totalPages}
          </span>
          <Button
            variant="ghost"
            size="icon"
            onClick={handleNext}
            disabled={!canNext}
            className="border border-white/10 bg-white/5 text-white hover:bg-white/10 disabled:opacity-40"
          >
            <ChevronRight className="size-4" />
            <span className="sr-only">Next page</span>
          </Button>
        </div>
      </CardFooter>
    </Card>
  )
}


