"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Playfair_Display } from "next/font/google"
import { Menu, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const playfair = Playfair_Display({ subsets: ["latin"], weight: ["400", "500", "600", "700"] })

type DashboardHeaderProps = {
	userName?: string
	username: string
	userRole?: "admin" | "staff" | "viewer"
	onLogout?: () => void
}

export function DashboardHeader({ userName = "User", username, userRole, onLogout }: DashboardHeaderProps) {
	const pathname = usePathname()
	const [mobileNavOpen, setMobileNavOpen] = useState(false)

	const portfolioTypes = [
		{ name: "Dashboard", href: `/dashboard/${username}` },
		{ name: "Algorithmic Strategies", href: `/dashboard/${username}/alphas` },
		{ name: "Long-Term Strategies", href: `/dashboard/${username}/longterm` },
		{ name: "Intraday Strategies", href: `/dashboard/${username}/intraday` },
		{ name: "Objectives", href: `/dashboard/${username}/objectives` },
		{ name: "Observability", href: `/dashboard/${username}/observability` },
	]

	const isAdmin = userRole === "admin"

	const handleLogout = () => {
		if (onLogout) {
			onLogout()
		} else {
			if (typeof window !== "undefined") {
				localStorage.clear()
				document.cookie = "access_token=; path=/; max-age=0"
				document.cookie = "refreshToken=; path=/; max-age=0"
			}
			window.location.href = "/login"
		}
	}

	useEffect(() => {
		setMobileNavOpen(false)
	}, [pathname])

	return (
		<>
			<header className="fixed inset-x-0 top-0 z-50 border-b border-white/10 bg-background/90 backdrop-blur-md">
				<div className="mx-auto flex max-w-screen-2xl items-center justify-between gap-2 px-4 py-3 sm:px-6 sm:py-4 lg:px-10">
					<div className="flex items-center gap-2">
						<button
							type="button"
							aria-expanded={mobileNavOpen}
							aria-label="Toggle navigation"
							onClick={() => setMobileNavOpen((prev) => !prev)}
							className="inline-flex items-center justify-center rounded-md border border-white/15 bg-black/40 p-2 text-white transition hover:border-white/30 hover:bg-black/55 sm:hidden"
						>
							{mobileNavOpen ? <X size={18} /> : <Menu size={18} />}
						</button>
						<span className={cn("text-base font-semibold text-[#fafafa] sm:text-lg", playfair.className)}>
							Hello, {userName}
						</span>
					</div>

					<nav className="hidden items-center gap-2 sm:flex">
						{portfolioTypes.map((type) => {
							const isActive = pathname === type.href
							return (
								<Link
									key={type.name}
									href={type.href}
									className={cn(
										"rounded-md px-3 py-2 text-base font-medium transition",
										isActive ? "bg-white/10 text-[#fafafa]" : "text-white/60 hover:text-white/90 hover:bg-white/5"
									)}
								>
									{type.name}
								</Link>
							)
						})}
						{isAdmin && (
							<Link
								href="/admin"
								className={cn(
									"rounded-md px-3 py-2 text-base font-medium transition",
									pathname === "/admin"
										? "bg-white/10 text-[#fafafa]"
										: "text-white/60 hover:text-white/90 hover:bg-white/5"
								)}
							>
								Admin
							</Link>
						)}
					</nav>

					<Button
						onClick={handleLogout}
						variant="outline"
						className="rounded-md border border-white/15 bg-black/35 px-4 py-2 text-base font-semibold text-[#fafafa] transition hover:-translate-y-0.5 hover:border-white/30 hover:bg-black/60"
					>
						Logout
					</Button>
				</div>

				{mobileNavOpen ? (
					<div className="border-t border-white/10 bg-background/95 shadow-lg sm:hidden">
						<nav className="flex flex-col gap-1 px-4 py-4">
							{portfolioTypes.map((type) => {
								const isActive = pathname === type.href
								return (
									<Link
										key={type.name}
										href={type.href}
										className={cn(
											"rounded-lg px-3 py-2 text-base font-medium",
											isActive ? "bg-white/15 text-[#fafafa]" : "text-white/70 hover:bg-white/10"
										)}
									>
										{type.name}
									</Link>
								)
							})}
							{isAdmin && (
								<Link
									href="/admin"
									className={cn(
										"rounded-lg px-3 py-2 text-base font-medium",
										pathname === "/admin" ? "bg-white/15 text-[#fafafa]" : "text-white/70 hover:bg-white/10"
									)}
								>
									Admin
								</Link>
							)}
						</nav>
					</div>
				) : null}
			</header>
			<div className="h-16 sm:h-[76px]" />
		</>
	)
}

