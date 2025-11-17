import * as React from "react"
import { cn } from "@/lib/utils"

export interface PageHeadingProps {
  tagline?: string
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}

export function PageHeading({
  tagline,
  title,
  description,
  action,
  className,
}: PageHeadingProps) {
  return (
    <header
      className={cn(
        "flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between",
        className
      )}
    >
      <div>
        <div>
          {tagline && (
            <p className="text-xs uppercase tracking-[0.3em] text-white/45">
              {tagline}
            </p>
          )}
          <h1 className="mt-2 text-4xl font-semibold text-[#fafafa]">
            {title}
          </h1>
          {description && (
            <p className="mt-2 text-sm text-white/60">{description}</p>
          )}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </header>
  )
}

