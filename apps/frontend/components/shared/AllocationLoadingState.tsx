"use client"

interface AllocationLoadingStateProps {
  title?: string
  description?: string
  steps?: string[]
  className?: string
  asCard?: boolean
}

export function AllocationLoadingState({
  title = "Allocating Your Portfolio",
  description = "We're setting up your trading agents and allocating your portfolio. This usually takes a few moments.",
  steps = [
    "Creating agent instances...",
    "Calculating optimal allocations...",
    "Initializing trading strategies...",
  ],
  className = "",
  asCard = false,
}: AllocationLoadingStateProps) {
  const content = (
    <>
      <div className="relative">
        <div className="h-16 w-16 animate-spin rounded-full border-4 border-white/10 border-t-amber-400" />
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="h-8 w-8 rounded-full bg-amber-400/20" />
        </div>
      </div>
      <div className="space-y-2">
        <h3 className="text-base font-semibold text-amber-200">{title}</h3>
        <p className="text-xs leading-relaxed text-white/60">{description}</p>
      </div>
      <div className="flex flex-col space-y-2 text-xs text-white/45">
        {steps.map((step, index) => (
          <div key={index} className="flex items-center space-x-2">
            <div
              className="h-2 w-2 animate-pulse rounded-full bg-amber-400"
              style={{ animationDelay: `${index * 200}ms` }}
            />
            <span>{step}</span>
          </div>
        ))}
      </div>
    </>
  )

  if (asCard) {
    return (
      <div
        className={`card-glass flex h-full flex-col items-center justify-center space-y-6 rounded-2xl border border-amber-500/20 bg-gradient-to-br from-amber-500/10 to-orange-500/5 p-8 text-center shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur ${className}`}
      >
        {content}
      </div>
    )
  }

  return (
    <div
      className={`flex flex-col items-center justify-center space-y-4 rounded-xl border border-amber-500/20 bg-gradient-to-br from-amber-500/10 to-orange-500/5 p-8 text-center ${className}`}
    >
      {content}
    </div>
  )
}

