import type { ReactNode } from "react"

export function DetailRow({
  label,
  value,
  valueClassName,
}: {
  label: string
  value: string | ReactNode | null
  valueClassName?: string
}) {
  if (!value) {
    return null
  }

  return (
    <div className="flex flex-wrap justify-between gap-2 text-xs uppercase tracking-[0.25em] text-white/60">
      <span>{label}</span>
      <span className={`font-semibold ${valueClassName ?? "text-white/80"}`}>{value}</span>
    </div>
  )
}

