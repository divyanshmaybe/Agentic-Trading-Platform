import Link from "next/link"
import { Button } from "@/components/ui/button"

interface NoPortfolioStateProps {
  username: string
}

export function NoPortfolioState({ username }: NoPortfolioStateProps) {
  return (
    <div className="card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur p-8 h-full flex items-center justify-center">
      <div className="flex flex-col items-center justify-center text-center space-y-4">
        <h3 className="text-2xl font-semibold text-[#fafafa]">No Portfolio Found</h3>
        <p className="text-white/60 max-w-md">
          You don't have a portfolio set up yet. Set your investment objectives to create your portfolio and start trading.
        </p>
        <Button asChild className="mt-4 bg-gradient-to-r from-[#1E1E3F] to-[#2B6CB0] text-white hover:opacity-90">
          <Link href={`/dashboard/${username}/objectives`}>
            Set Investment Objectives
          </Link>
        </Button>
      </div>
    </div>
  )
}

