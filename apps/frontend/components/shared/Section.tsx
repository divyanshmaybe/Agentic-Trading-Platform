import * as React from "react"
import { cn } from "@/lib/utils"
import { Separator } from "@/components/ui/separator"

export function Section({
  className,
  id,
  children,
  ...props
}: React.HTMLAttributes<HTMLElement> & { id?: string }) {
  return (
    <section id={id} className={cn("py-20 sm:py-28", className)} {...props}>
      {children}
    </section>
  )
}

export function SectionHeader({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow?: string
  title: string
  subtitle?: string
}) {
  return (
    <div className="mx-auto max-w-3xl text-center">
      {eyebrow ? (
        <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300">
          {eyebrow}
        </div>
      ) : null}
      <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h2>
      {subtitle ? (
        <p className="mt-3 text-base text-muted-foreground">{subtitle}</p>
      ) : null}
      <Separator className="mx-auto mt-8 w-24" />
    </div>
  )
}


