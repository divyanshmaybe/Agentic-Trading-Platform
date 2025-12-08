"use client"
import { Button } from "@/components/ui/button"
import { motion } from "framer-motion"
import Image from "next/image"

export default function Hero() {
  return (
    <section className="relative h-[90vh] flex flex-col justify-center items-center text-center bg-gradient-to-b from-[var(--gradient-from)] to-[var(--gradient-to)]">
      <motion.h1
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8 }}
        className="text-5xl font-bold text-primary relative z-10"
      >
        To intelligence shaping enterprise evolution.
      </motion.h1>
      <p className="max-w-2xl mt-4 relative z-10">
        Empowering businesses through the Pathway Framework for performance-driven portfolio management.
      </p>
      <div className="mt-6 flex gap-4 relative z-10">
        <Button asChild>
          <a href="/login">Get Started</a>
        </Button>
        <Button variant="outline">View Platform</Button>
      </div>
      <Image src="/images/hero-bg.jpg" alt="Hero Background" fill className="object-cover opacity-50 absolute top-0 z-0" />
    </section>
  )
}


