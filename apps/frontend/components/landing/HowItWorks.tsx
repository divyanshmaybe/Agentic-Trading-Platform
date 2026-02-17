import { Container } from "@/components/shared/Container"
import { Section, SectionHeader } from "@/components/shared/Section"
import { steps } from "@/lib/marketing"

export function HowItWorks() {
  return (
    <Section id="how-it-works">
      <Container>
        <SectionHeader
          eyebrow="How it works"
          title="From connection to continuous control"
          subtitle="Start safe, scale fast, stay in control at every step."
        />
        <ol className="mx-auto mt-10 grid max-w-3xl gap-6">
          {steps.map((s) => (
            <li key={s.number} className="flex items-start gap-4">
              <div className="mt-1 inline-flex size-8 items-center justify-center rounded-full bg-indigo-600 text-white">
                <span className="text-sm font-semibold">{s.number}</span>
              </div>
              <div>
                <h3 className="font-medium">{s.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{s.description}</p>
              </div>
            </li>
          ))}
        </ol>
      </Container>
    </Section>
  )
}


