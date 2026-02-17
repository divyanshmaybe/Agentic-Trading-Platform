import Image from "next/image"
import Link from "next/link"
import { Container } from "@/components/shared/Container"
import { Section } from "@/components/shared/Section"
import { hero } from "@/lib/marketing"
import { FadeIn } from "@/components/shared/FadeIn"

export function Hero() {
  return (
    <Section className="relative min-h-[100svh] overflow-hidden py-0">
      <div className="pointer-events-none absolute inset-0">
        <Image
          src="/images/hero-bg.jpg"
          alt="Lower Manhattan skyline at dusk"
          fill
          priority
          className="object-cover mask-fade-b-into-bg"
        />
        <div className="absolute inset-0 [background-image:radial-gradient(1200px_circle_at_50%_-20%,rgba(37,99,235,.25),transparent_60%),radial-gradient(800px_circle_at_80%_20%,rgba(124,58,237,.2),transparent_50%)]" />
      </div>

      <Container>
			  <FadeIn className="relative mx-auto flex min-h-[90vh] max-w-3xl flex-col items-center justify-center text-center px-4 -translate-y-12 sm:-translate-y-20 md:-translate-y-28 lg:-translate-y-32">
				  <h1 className="text-4xl font-medium tracking-tight sm:text-5xl text-[#111827] drop-shadow-[0_1px_1.5px_rgba(0,0,0,0.15)] -translate-y-12 sm:-translate-y-20 md:-translate-y-28 lg:-translate-y-32">
            {hero.title}
          </h1>
				  <p className="mx-auto mt-4 max-w-2xl text-lg text-[#374151] drop-shadow-[0_1px_1.5px_rgba(0,0,0,0.12)] -translate-y-12 sm:-translate-y-20 md:-translate-y-28 lg:-translate-y-32 font-playfair">
            {hero.description}
          </p>
        </FadeIn>
      </Container>

      {/* Subtle floating accent */}
      <div className="pointer-events-none absolute -left-10 top-1/3 h-72 w-72 rounded-full bg-cyan-500/10 blur-3xl" />
      <div className="pointer-events-none absolute -right-10 bottom-1/4 h-72 w-72 rounded-full bg-purple-500/10 blur-3xl" />
    </Section>
  )
}


