"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"

interface ReasoningCardProps {
	label: string
	percentage: number
	reasoning?: string
}

export function ReasoningCard({ label, percentage, reasoning }: ReasoningCardProps) {
	const [isHovered, setIsHovered] = useState(false)

	return (
		<div
			className="relative rounded-lg border border-white/10 bg-black/20 p-3 transition-all hover:bg-black/30 hover:border-white/20"
			onMouseEnter={() => setIsHovered(true)}
			onMouseLeave={() => setIsHovered(false)}
		>
			<div className="flex items-center justify-between">
				<span className="font-medium text-[#fafafa]">{label}</span>
				<span className="text-sm text-white/70">{percentage.toFixed(2)}%</span>
			</div>
			<AnimatePresence>
				{isHovered && reasoning && (
					<motion.div
						initial={{ opacity: 0, height: 0, marginTop: 0 }}
						animate={{ opacity: 1, height: "auto", marginTop: 8 }}
						exit={{ opacity: 0, height: 0, marginTop: 0 }}
						transition={{ duration: 0.2, ease: "easeInOut" }}
						className="overflow-hidden"
					>
						<p className="text-sm text-white/60 leading-relaxed">{reasoning}</p>
					</motion.div>
				)}
			</AnimatePresence>
		</div>
	)
}
