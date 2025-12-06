"use client"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type AppHeaderProps = {
	className?: string
	title?: string
	subtitle?: string
	onLogout?: () => void
}

export function AppHeader({ className, title = "AgentInvest", subtitle, onLogout }: AppHeaderProps) {
	return (
		<header
			className={cn(
				"sticky top-0 z-30 w-full border-b border-white/10 bg-black/60 backdrop-blur",
				className,
			)}
		>
			<div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-5">
				<div className="flex items-baseline gap-3 text-white">
					<h1 className="font-playfair text-3xl tracking-[0.2em]">{title}</h1>
					{subtitle ? (
						<span className="font-playfair text-xl text-white/70">({subtitle})</span>
					) : null}
				</div>
				<Button
					onClick={onLogout}
					variant="outline"
					className="h-10 rounded-xl border-white/40 px-6 text-base font-medium text-white hover:bg-white/20"
				>
					Logout
				</Button>
			</div>
		</header>
	)
}

