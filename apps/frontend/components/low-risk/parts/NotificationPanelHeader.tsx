import { CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export function NotificationPanelHeader({ activeTopics }: { activeTopics: string[] }) {
  return (
    <CardHeader className="space-y-2 pb-5">
      <CardDescription className="text-xs uppercase tracking-[0.3em] text-white/45">
        Low-Risk Streams
      </CardDescription>
      <CardTitle className="h-title text-xl text-[#fafafa]">Live Portfolio Notifications</CardTitle>
      {activeTopics.length ? (
        <p className="text-[11px] text-white/50">
          Tracking: <NotificationActiveTopics topics={activeTopics} />
        </p>
      ) : null}
    </CardHeader>
  )
}

function NotificationActiveTopics({ topics }: { topics: string[] }) {
  return <span className="font-semibold text-white/70">{topics.join(", ")}</span>
}

