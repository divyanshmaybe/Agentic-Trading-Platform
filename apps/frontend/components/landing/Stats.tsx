import { Container } from "@/components/shared/Container"
import { Section, SectionHeader } from "@/components/shared/Section"
import { kpis } from "@/lib/marketing"

export function Stats() {
  return (
    <Section id="stats">
      <Container>
        <SectionHeader
          eyebrow="Impact"
          title="Operational and analytical scale"
          subtitle="Designed for high-throughput, low-latency decisioning."
        />
        <div className="mx-auto mt-10 grid max-w-3xl grid-cols-2 gap-6 sm:grid-cols-4">
          {kpis.map((kpi) => (
            <div key={kpi.label} className="text-center">
              <div className="text-2xl font-semibold text-indigo-600 sm:text-3xl">
                {kpi.value}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">{kpi.label}</div>
            </div>
          ))}
        </div>
      </Container>
    </Section>
  )
}


