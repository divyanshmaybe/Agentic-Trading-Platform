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
			className="relative flex items-center justify-between gap-4 rounded-xl border border-white/5 bg-[#1b1b1b] p-4 transition-all hover:bg-[#242424] hover:border-white/20 hover:translate-y-px hover:shadow-[0_18px_40px_rgba(0,0,0,0.55)]"
			onMouseEnter={() => setIsHovered(true)}
			onMouseLeave={() => setIsHovered(false)}
		>
			<div className="flex min-w-0 items-center gap-3">
				<span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/5 text-base">
					💼
				</span>
				<div className="min-w-0">
					<div className="text-sm font-semibold text-white">{label}</div>
					<AnimatePresence>
						{isHovered && reasoning && (
							<motion.div
								initial={{ opacity: 0, height: 0, marginTop: 0 }}
								animate={{ opacity: 1, height: "auto", marginTop: 4 }}
								exit={{ opacity: 0, height: 0, marginTop: 0 }}
								transition={{ duration: 0.2, ease: "easeInOut" }}
								className="overflow-hidden"
							>
								<p className="text-xs text-gray-400 leading-relaxed truncate">
									{reasoning}
								</p>
							</motion.div>
						)}
					</AnimatePresence>
				</div>
			</div>
			<div className="text-right text-sm font-semibold text-emerald-400">
				{percentage.toFixed(2)}%
			</div>
		</div>
	)
}
