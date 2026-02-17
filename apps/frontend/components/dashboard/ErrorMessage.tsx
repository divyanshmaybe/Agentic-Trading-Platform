interface ErrorMessageProps {
  title: string
  message: string
}

export function ErrorMessage({ title, message }: ErrorMessageProps) {
  return (
    <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-400">
      <p className="font-semibold">{title}</p>
      <p>{message}</p>
    </div>
  )
}

