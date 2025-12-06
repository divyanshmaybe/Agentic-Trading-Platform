"use client"

import { Calendar, Clock, AlertCircle } from "lucide-react"
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"

interface CooldownModalProps {
	open: boolean
	onOpenChange: (open: boolean) => void
	daysElapsed: number
	daysRemaining: number
	message: string
}

export function CooldownModal({
	open,
	onOpenChange,
	daysElapsed,
	daysRemaining,
	message,
}: CooldownModalProps) {
	const totalDays = 180 // 6 months ≈ 180 days
	const progressPercentage = (daysElapsed / totalDays) * 100

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-w-lg bg-[#0c0c0c] border-amber-500/30 text-[#fafafa] shadow-2xl">
				<DialogHeader className="space-y-4">
					{/* Icon and Title */}
					<div className="flex flex-col items-center gap-4 pt-2">
						<div className="relative">
							{/* Animated background glow */}
							<div className="absolute inset-0 animate-pulse rounded-full bg-amber-500/20 blur-xl"></div>
							{/* Icon container */}
							<div className="relative rounded-full border-2 border-amber-500/40 bg-amber-500/10 p-4">
								<Clock className="h-10 w-10 text-amber-400" />
							</div>
						</div>
						<div className="text-center">
							<DialogTitle className="text-2xl font-semibold text-white">
								Rebalance Cooldown Active
							</DialogTitle>
							<DialogDescription className="mt-2 text-white/60">
								The low-risk portfolio has a 6-month rebalancing restriction to ensure long-term
								stability and optimal performance.
							</DialogDescription>
						</div>
					</div>
				</DialogHeader>

				{/* Stats Cards */}
				<div className="grid grid-cols-2 gap-4 py-6">
					{/* Days Elapsed */}
					<div className="rounded-xl border border-white/10 bg-gradient-to-br from-white/8 to-white/4 p-4 backdrop-blur-sm">
						<div className="flex items-center gap-2 text-white/60 mb-2">
							<Calendar className="h-4 w-4" />
							<span className="text-xs font-medium uppercase tracking-wide">Days Elapsed</span>
						</div>
						<div className="text-3xl font-bold text-white">{daysElapsed}</div>
						<div className="mt-1 text-xs text-white/50">since last run</div>
					</div>

					{/* Days Remaining */}
					<div className="rounded-xl border border-amber-500/30 bg-gradient-to-br from-amber-500/15 to-amber-500/5 p-4 backdrop-blur-sm">
						<div className="flex items-center gap-2 text-amber-400/80 mb-2">
							<AlertCircle className="h-4 w-4" />
							<span className="text-xs font-medium uppercase tracking-wide">Days Remaining</span>
						</div>
						<div className="text-3xl font-bold text-amber-300">{daysRemaining}</div>
						<div className="mt-1 text-xs text-amber-400/60">until next rebalance</div>
					</div>
				</div>

				{/* Progress Bar */}
				<div className="space-y-3 pb-2">
					<div className="flex items-center justify-between text-sm">
						<span className="text-white/60">Cooldown Progress</span>
						<span className="font-medium text-white">{progressPercentage.toFixed(1)}%</span>
					</div>
					<div className="h-3 overflow-hidden rounded-full border border-white/10 bg-white/5">
						<div
							className="h-full rounded-full bg-gradient-to-r from-amber-500 to-orange-500 transition-all duration-500 ease-out"
							style={{ width: `${progressPercentage}%` }}
						>
							<div className="h-full w-full animate-pulse bg-gradient-to-r from-transparent via-white/20 to-transparent"></div>
						</div>
					</div>
					<div className="flex justify-between text-xs text-white/40">
						<span>Last Run</span>
						<span>6 Months Complete</span>
					</div>
				</div>

				{/* Message Display */}
				<div className="rounded-lg border border-white/10 bg-white/5 p-4 mt-2">
					<p className="text-sm text-white/70 leading-relaxed">
						{message}
					</p>
				</div>

				{/* Action Button */}
				<div className="flex justify-center pt-4">
					<Button
						onClick={() => onOpenChange(false)}
						className="min-w-[200px] border border-white/20 bg-white/10 text-white hover:bg-white/20 transition-colors"
					>
						Got it
					</Button>
				</div>
			</DialogContent>
		</Dialog>
	)
}

