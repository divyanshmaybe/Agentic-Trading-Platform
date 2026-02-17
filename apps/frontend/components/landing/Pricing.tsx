import Link from "next/link"
import { Container } from "@/components/shared/Container"
import { Section, SectionHeader } from "@/components/shared/Section"
import { ArrowRight } from "lucide-react"
import { FadeIn } from "@/components/shared/FadeIn"

export function Pricing() {
  return (
    <Section id="pricing">
      <Container>
        <FadeIn>
          <SectionHeader
            title="Unbeatable pricing"
            subtitle="Flat ₹20 intraday and F&O trades, ₹0 account opening, ₹0 equity delivery."
          />
          <div className="mt-6 text-center">
            <Link href="#" className="inline-flex items-center gap-1 text-sm font-medium text-foreground/90 hover:text-foreground">
              See pricing <ArrowRight className="size-4" />
            </Link>
          </div>
        </FadeIn>
      </Container>
    </Section>
  )
}


