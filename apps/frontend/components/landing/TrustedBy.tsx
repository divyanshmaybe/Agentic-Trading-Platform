import Image from "next/image"
import { Container } from "@/components/shared/Container"
import { Section } from "@/components/shared/Section"
import { logos } from "@/lib/marketing"
import { FadeIn } from "@/components/shared/FadeIn"

export function TrustedBy() {
  return (
    <Section aria-label="Trusted by" className="bg-background/60">
      <Container>
        <FadeIn className="mx-auto max-w-5xl">
          <p className="mb-6 text-center text-sm uppercase tracking-widest text-muted-foreground">
            Trusted by modern finance teams
          </p>
          <div className="grid grid-cols-2 items-center gap-6 opacity-80 sm:grid-cols-3 md:grid-cols-5">
            {logos.map((logo) => (
              <div key={logo.alt} className="relative h-10 w-full">
                <Image src={logo.src} alt={logo.alt} fill className="object-contain" />
              </div>
            ))}
          </div>
        </FadeIn>
      </Container>
    </Section>
  )
}
