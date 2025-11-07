import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"

import type { NotificationItem } from "@/lib/dashboardTypes"

type NotificationCardProps = {
  notification: NotificationItem | null
}

export function NotificationCard({ notification }: NotificationCardProps) {
  if (!notification) {
    return null
  }

  return (
    <Card className="card-glass neon-hover rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur">
      <CardHeader className="gap-1">
        <CardTitle className="h-title text-lg text-[#fafafa]">{notification.title}</CardTitle>
        <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
          Notifications
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-sm text-white/70">
        <p className="leading-relaxed text-white/70">{notification.body}</p>
        <div className="text-xs font-medium uppercase tracking-wide text-white/45">{notification.timestamp}</div>
      </CardContent>
      {notification.actions?.length ? (
        <CardFooter className="gap-3">
          {notification.actions.map((action) => (
            <Button
              key={`${notification.id}-${action.value}`}
              size="sm"
              variant="outline"
              className="neon-hover rounded-lg border border-white/15 bg-white/5 px-4 text-xs font-semibold text-[#fafafa] transition hover:-translate-y-0.5 hover:border-white/25 hover:bg-white/10"
            >
              {action.label}
            </Button>
          ))}
        </CardFooter>
      ) : null}
    </Card>
  )
}

