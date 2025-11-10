export function NotificationIntro({ message }: { message: string | null }) {
  if (!message) {
    return null
  }

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-sm text-white/70">
      {message}
    </div>
  )
}

