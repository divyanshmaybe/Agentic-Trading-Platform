export function NotificationIntro({ message }: { message: string | null }) {
  if (!message) {
    return null
  }

  return (
    <div className="rounded-xl border border-white/12 bg-black/25 p-4 text-sm text-white/70 shadow-[0_10px_30px_-18px_rgba(0,0,0,0.8)]">
      {message}
    </div>
  )
}

