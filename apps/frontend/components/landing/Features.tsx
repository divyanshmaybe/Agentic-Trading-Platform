import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Container } from "@/components/shared/Container"
import { Section, SectionHeader } from "@/components/shared/Section"
import { features } from "@/lib/marketing"
import {
  LineChart,
  ShieldCheck,
  Zap,
  Brain,
  BarChart3,
  Lock,
} from "lucide-react"
import { FadeIn } from "@/components/shared/FadeIn"

const iconMap = {
  LineChart,
  ShieldCheck,
  Zap,
  Brain,
  BarChart3,
  Lock,
}

export function Features() {
  return (
    <Section id="features">
      <Container>
        <SectionHeader
          eyebrow="Features"
          title="AI that thinks, trades, and evolves"
          subtitle="Agentic intelligence, risk adaptation, real-time insights, and transparency by default."
        />
        <FadeIn>
          <div className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {features.map((f) => {
              const Icon = iconMap[f.icon]
              return (
                <Card key={f.title} className="h-full transition-transform duration-200 hover:-translate-y-0.5">
                  <CardHeader>
                    <div className="mb-3 inline-flex size-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10">
                      <Icon className="size-5" />
                    </div>
                    <CardTitle>{f.title}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-muted-foreground">{f.description}</p>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        </FadeIn>
      </Container>
    </Section>
  )
}


