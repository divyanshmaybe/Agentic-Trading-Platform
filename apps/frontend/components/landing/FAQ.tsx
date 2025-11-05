import { Container } from "@/components/shared/Container"
import { Section, SectionHeader } from "@/components/shared/Section"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { faqs } from "@/lib/marketing"

export function FAQ() {
  return (
    <Section id="faq">
      <Container>
        <SectionHeader
          eyebrow="FAQ"
          title="Answers to common questions"
          subtitle="If you don’t find what you’re looking for, reach out."
        />
        <div className="mx-auto mt-10 max-w-3xl">
          <Accordion type="single" collapsible defaultValue={faqs[0]?.q}>
            {faqs.map((f) => (
              <AccordionItem key={f.q} value={f.q}>
                <AccordionTrigger>{f.q}</AccordionTrigger>
                <AccordionContent>{f.a}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      </Container>
    </Section>
  )
}


