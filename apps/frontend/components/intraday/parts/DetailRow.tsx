export function DetailRow({ label, value }: { label: string; value: string | null }) {
  if (!value) {
    return null
  }

  return (
    <div className="flex flex-wrap justify-between gap-2 text-xs uppercase tracking-[0.25em] text-white/60">
      <span>{label}</span>
      <span className="font-semibold text-white/80">{value}</span>
    </div>
  )
}

