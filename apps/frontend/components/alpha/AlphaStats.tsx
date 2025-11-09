"use client"

import { motion, type Variants } from "framer-motion"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { alphaStats } from "@/mock/alphaData"

const container: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: {
    opacity: 1,
    y: 0,
    transition: { staggerChildren: 0.08, duration: 0.4, ease: [0.37, 0, 0.63, 1] },
  },
}

const item: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0 },
}

export function AlphaStats() {
  return (
    <Card className="card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader>
        <CardTitle className="h-title text-xl text-[#fafafa]">Stats</CardTitle>
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Portfolio snapshot
        </CardDescription>
      </CardHeader>
      <CardContent>
        <motion.div
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
          variants={container}
          initial="hidden"
          animate="show"
        >
          {alphaStats.map((stat) => (
            <motion.div
              key={stat.label}
              variants={item}
              className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm"
            >
              <p className="text-xs uppercase tracking-wide text-white/45">{stat.label}</p>
              <p className="mt-2 text-2xl font-semibold text-[#fafafa]">{stat.value}</p>
              {stat.helper ? <p className="mt-1 text-xs text-white/55">{stat.helper}</p> : null}
            </motion.div>
          ))}
        </motion.div>
      </CardContent>
    </Card>
  )
}


