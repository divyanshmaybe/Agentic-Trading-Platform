export function AllocationWarning() {
  return (
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-400">
      <p className="font-semibold">Portfolio Allocation Unavailable</p>
      <p className="mt-1">
        We're currently balancing your investments between long-term, intraday, and algorithmic trading strategies based on your objectives. 
        Allocation details will be available once the portfolio setup is complete.
      </p>
    </div>
  )
}

