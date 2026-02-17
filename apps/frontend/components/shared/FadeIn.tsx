"use client"
import { motion, useReducedMotion } from "framer-motion"
import * as React from "react"

export function FadeIn({ children, className }: { children: React.ReactNode; className?: string }) {
  const prefersReduced = useReducedMotion()
  return (
    <motion.div
      className={className}
      initial={prefersReduced ? false : { opacity: 0, y: 8 }}
      whileInView={prefersReduced ? {} : { opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  )
}


