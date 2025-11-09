"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Playfair_Display } from "next/font/google"
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

  const portfolioTypes = [
    { name: "Dashboard", href: `/dashboard/${username}` },
    { name: "Alphas", href: `/dashboard/${username}/alphas` },
    { name: "High-Risk", href: `/dashboard/${username}/high-risk` },
    { name: "Low-Risk", href: `/dashboard/${username}/low-risk` },
  ]
  
  const isAdmin = userRole === "admin"

  const handleLogout = () => {
    if (onLogout) {
      onLogout()
    } else {
      // Clear localStorage
      if (typeof window !== "undefined") {
        localStorage.clear()
        // Clear cookies
        document.cookie = "access_token=; path=/; max-age=0"
        document.cookie = "refreshToken=; path=/; max-age=0"
      }
      // Redirect to login
      window.location.href = "/login"
    }
  }

  return (
    <>
      <header className="fixed inset-x-0 top-0 z-50 h-16 border-b border-white/10 bg-background/80 backdrop-blur-md shadow-sm">
      <div className="flex h-full items-center justify-between px-4 sm:px-8">
        {/* Left: Greeting + Admin Link (if admin) + Navigation */}
        <div className="flex items-center gap-8">
          {/* Greeting */}
          <div className="flex flex-col">
            <span className={cn("text-2xl font-semibold text-[#fafafa]", playfair.className)}>
              Hello, {userName}
            </span>
            <span className="text-xs text-white/50">Welcome to your trading desk</span>
          </div>

          {/* Admin Link - After Greeting */}
          {isAdmin && (
            <>
              <div className="h-8 w-px bg-white/10" />
              <Link
                href="/admin"
                className={cn(
                  "relative px-5 py-2 text-sm font-medium transition-all duration-200",
                  "rounded-lg",
                  pathname === "/admin"
                    ? "text-[#fafafa] bg-white/10"
                    : "text-white/60 hover:text-white/90 hover:bg-white/5"
                )}
              >
                Admin
                {pathname === "/admin" && (
                  <span className="absolute inset-x-0 -bottom-[1.3rem] h-[2px] bg-linear-to-r from-blue-500 via-purple-500 to-cyan-500" />
                )}
              </Link>
            </>
          )}

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
    <div className="h-16" />
    </>
  )
}

