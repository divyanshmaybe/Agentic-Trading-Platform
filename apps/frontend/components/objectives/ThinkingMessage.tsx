"use client"

export function ThinkingMessage() {
  return (
    <div className="flex w-full justify-start">
      <div className="max-w-[80%] rounded-lg bg-white/6 px-4 py-3 text-sm text-white/90">
        <div className="flex items-center gap-1">
          <span>Thinking</span>
          <div className="flex gap-1">
            <span
              className="inline-block animate-pulse"
              style={{ animationDelay: "0ms" }}
            >
              .
            </span>
            <span
              className="inline-block animate-pulse"
              style={{ animationDelay: "200ms" }}
            >
              .
            </span>
            <span
              className="inline-block animate-pulse"
              style={{ animationDelay: "400ms" }}
            >
              .
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

