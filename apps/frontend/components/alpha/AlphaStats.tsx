"use client"

import { motion, type Variants } from "framer-motion"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
    <Card className="card-glass neon-hover rounded-2xl border border-white/10 bg-black/40 shadow-xl">
      <CardHeader>
        <CardTitle className="h-title text-xl text-white">Stats</CardTitle>
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
              className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur"
            >
              <p className="text-xs uppercase tracking-wider text-white/60">{stat.label}</p>
              <p className="mt-2 text-2xl font-semibold text-white">{stat.value}</p>
              {stat.helper ? <p className="mt-1 text-xs text-white/50">{stat.helper}</p> : null}
            </motion.div>
          ))}
        </motion.div>
      </CardContent>
    </Card>
  )
}


