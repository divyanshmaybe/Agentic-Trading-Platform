"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Playfair_Display } from "next/font/google"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const playfair = Playfair_Display({ subsets: ["latin"], weight: ["400", "500", "600", "700"] })

type DashboardHeaderProps = {
  userName?: string
  onLogout?: () => void
}

const portfolioTypes = [
  { name: "Dashboard", href: "/dashboard" },
  { name: "Alphas", href: "/dashboard/alphas" },
  { name: "High-Risk", href: "/dashboard/high-risk" },
  { name: "Low-Risk", href: "/dashboard/low-risk" },
]

export function DashboardHeader({ userName = "Aayush", onLogout }: DashboardHeaderProps) {
  const pathname = usePathname()

  const handleLogout = () => {
    if (onLogout) {
      onLogout()
    } else {
      // Default logout behavior
      window.location.href = "/login"
    }
  }

  return (
    <header className="sticky h-[10vh]  top-0 z-40 w-full border-b border-white/10 bg-black/80 backdrop-blur-xl">
      <div className="flex h-full items-center justify-between px-8">
        {/* Left: Greeting */}
        <div className="flex items-center gap-8">
          <div className="flex flex-col">
            <span className={cn("text-2xl font-semibold text-[#fafafa]", playfair.className)}>
              Hello, {userName}
            </span>
            <span className="text-xs text-white/50">Welcome to your trading desk</span>
          </div>

          {/* Navigation Tabs */}
          <nav className="hidden md:flex items-center gap-2">
            {portfolioTypes.map((type) => {
              const isActive = pathname === type.href
              
              return (
                <Link
                  key={type.name}
                  href={type.href}
                  className={cn(
                    "relative px-5 py-2 text-sm font-medium transition-all duration-200",
                    "rounded-lg",
                    isActive
                      ? "text-[#fafafa] bg-white/10"
                      : "text-white/60 hover:text-white/90 hover:bg-white/5"
                  )}
                >
                  {type.name}
                  {isActive && (
                    <span className="absolute inset-x-0 -bottom-[1.3rem] h-[2px] bg-gradient-to-r from-blue-500 via-purple-500 to-cyan-500" />
                  )}
                </Link>
              )
            })}
          </nav>
        </div>

        {/* Right: Logout */}
        <Button
          onClick={handleLogout}
          variant="outline"
          className="neon-hover rounded-lg border border-white/15 bg-black/40 px-6 py-2 text-sm font-semibold text-[#fafafa] transition hover:-translate-y-0.5 hover:border-white/30 hover:bg-black/60"
        >
          Logout
        </Button>
      </div>
    </header>
  )
}

