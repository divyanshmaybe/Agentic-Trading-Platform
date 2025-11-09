"use client"

import { motion, type Variants } from "framer-motion"
import { ArrowDownRight, ArrowUpRight } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { alphaStats, topAlphas } from "@/mock/alphaData"

const listVariants: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: {
    opacity: 1,
    y: 0,
    transition: { staggerChildren: 0.06, delayChildren: 0.1 },
  },
}

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.37, 0, 0.63, 1] } },
}

export function TopAlphas() {
  return (
    <Card className="card-glass neon-hover rounded-2xl border border-white/10 bg-black/40 shadow-xl">
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle className="h-title text-xl text-white">Top 10 Alphas</CardTitle>
          <p className="mt-1 text-xs text-white/60">Sorted by trailing 7-day performance</p>
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-wide text-white/50">Avg. Return</p>
          <p className="text-lg font-semibold text-emerald-400">
            {alphaStats.find((stat) => stat.label === "Current Returns")?.value ?? "18.4%"}
          </p>
        </div>
      </CardHeader>
      <CardContent>
        <div className="relative">
          <motion.ul
            variants={listVariants}
            initial="hidden"
            animate="show"
            className="space-y-3 overflow-y-auto pr-2"
            style={{ maxHeight: "320px" }}
          >
            {topAlphas.map((alpha) => {
              const isUp = alpha.direction === "up"
              const Icon = isUp ? ArrowUpRight : ArrowDownRight
              return (
                <motion.li
                  key={alpha.id}
                  variants={itemVariants}
                  className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-4 py-3 backdrop-blur transition hover:border-white/20"
                >
                  <div className="flex flex-col gap-1">
                    <p className="text-sm font-medium text-white">{alpha.name}</p>
                    <span className="text-xs text-white/60">#{alpha.id.replace("alpha-", "")}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`text-sm font-semibold ${isUp ? "text-emerald-400" : "text-rose-400"}`}>
                      {alpha.returnPct > 0 ? "+" : ""}
                      {alpha.returnPct.toFixed(1)}%
                    </span>
                    <span
                      className={`flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium ${
                        isUp ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-200"
                      }`}
                    >
                      <Icon className="size-4" />
                      {isUp ? "Bullish" : "Bearish"}
                    </span>
                  </div>
                </motion.li>
              )
            })}
          </motion.ul>
        </div>
      </CardContent>
    </Card>
  )
}


