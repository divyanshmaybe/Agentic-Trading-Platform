"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Playfair_Display } from "next/font/google"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const playfair = Playfair_Display({ subsets: ["latin"], weight: ["400", "500", "600", "700"] })

type AdminHeaderProps = {
  userName?: string
  username?: string
  onLogout?: () => void
}

export function AdminHeader({ userName = "Admin", username, onLogout }: AdminHeaderProps) {
  const pathname = usePathname()

  // Dashboard navigation links (only show if username is provided)
  const dashboardLinks = username ? [
    { name: "Dashboard", href: `/dashboard/${username}` },
    { name: "Alphas", href: `/dashboard/${username}/alphas` },
    { name: "High-Risk", href: `/dashboard/${username}/high-risk` },
    { name: "Low-Risk", href: `/dashboard/${username}/low-risk` },
  ] : []

  const handleLogout = () => {
    if (onLogout) {
      onLogout()
    } else {
      // Clear localStorage and cookies
      if (typeof window !== "undefined") {
        localStorage.clear()
        document.cookie = "access_token=; path=/; max-age=0"
        document.cookie = "refreshToken=; path=/; max-age=0"
      }
      window.location.href = "/login"
    }
  }

  return (
    <header className="sticky h-[10vh] top-0 z-40 w-full border-b border-white/10 bg-black/80 backdrop-blur-xl">
      <div className="flex h-full items-center justify-between px-8">
        {/* Left: Admin Title & Navigation */}
        <div className="flex items-center gap-8">
          <div className="flex flex-col">
            <span className={cn("text-2xl font-semibold text-[#fafafa]", playfair.className)}>
              Admin Panel
            </span>
            <span className="text-xs text-white/50">Hello, {userName}</span>
          </div>

          {/* Navigation Tabs - Only show if username is available */}
          {dashboardLinks.length > 0 && (
            <>
              <div className="h-8 w-px bg-white/10" />
              <nav className="hidden md:flex items-center gap-2">
                {/* Admin Panel Link */}
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
                    <span className="absolute inset-x-0 -bottom-[1.3rem] h-[2px] bg-gradient-to-r from-blue-500 via-purple-500 to-cyan-500" />
                  )}
                </Link>

                {/* Dashboard Links */}
                {dashboardLinks.map((link) => {
                  const isActive = pathname === link.href
                  
                  return (
                    <Link
                      key={link.name}
                      href={link.href}
                      className={cn(
                        "relative px-5 py-2 text-sm font-medium transition-all duration-200",
                        "rounded-lg",
                        isActive
                          ? "text-[#fafafa] bg-white/10"
                          : "text-white/60 hover:text-white/90 hover:bg-white/5"
                      )}
                    >
                      {link.name}
                      {isActive && (
                        <span className="absolute inset-x-0 -bottom-[1.3rem] h-[2px] bg-gradient-to-r from-blue-500 via-purple-500 to-cyan-500" />
                      )}
                    </Link>
                  )
                })}
              </nav>
            </>
          )}
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

