import { PortfolioOverviewCard } from "./PortfolioOverviewCard"
import { StocksWatchlistCard } from "./StocksWatchlistCard"
import { NoPortfolioState } from "./NoPortfolioState"
import type { PortfolioSummary, StockItem } from "@/lib/dashboardTypes"

interface DashboardContentProps {
  portfolioNotFound: boolean
  portfolioSummary: PortfolioSummary
  stocks: StockItem[]
  loading: boolean
  username: string
}

export function DashboardContent({ 
  portfolioNotFound, 
  portfolioSummary, 
  stocks, 
  loading, 
  username 
}: DashboardContentProps) {
  if (portfolioNotFound) {
    return <NoPortfolioState username={username} />
  }

  return (
    <div className="flex flex-col gap-6 min-w-0">
      <div className="shrink-0">
        <PortfolioOverviewCard summary={portfolioSummary} loading={loading} />
      </div>
      <div className="shrink-0">
        <StocksWatchlistCard stocks={stocks} loading={loading} />
      </div>
    </div>
  )
}

