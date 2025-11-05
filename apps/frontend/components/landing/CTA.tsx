import Link from "next/link"
import { Container } from "@/components/shared/Container"
import { Section } from "@/components/shared/Section"
import { Button } from "@/components/ui/button"

export function CTA() {
  return (
    <Section id="cta" className="py-20">
      <Container>
        <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03] backdrop-blur-md p-10 text-white shadow-[0_20px_60px_-28px_rgba(43,108,176,0.35)]">
          <div className="pointer-events-none absolute inset-0 bg-gradient-glow opacity-50" />
          <div className="relative z-10">
            <h3 className="text-3xl font-semibold tracking-tight">Let AI Trade Smarter for You.</h3>
            <p className="mt-2 text-white/85">Join the beta or book a demo to see Pathway in your world.</p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Button asChild className="rounded-full bg-gradient-to-r from-[#1E1E3F] to-[#2B6CB0] text-white ring-1 ring-white/10 shadow-[0_10px_30px_-12px_rgba(43,108,176,0.7)] hover:shadow-[0_12px_40px_-12px_rgba(43,108,176,0.85)] hover:ring-blue-400/30">
                <Link href="#signup">Join Beta</Link>
              </Button>
              <Button asChild variant="outline" className="rounded-full border-white/20 text-white hover:bg-white/5 hover:ring-1 hover:ring-blue-400/30">
                <Link href="#demo">Book a Demo</Link>
              </Button>
            </div>
          </div>
          <div className="pointer-events-none absolute -right-20 -top-20 size-72 rounded-full bg-[radial-gradient(50%_50%_at_50%_50%,rgba(43,108,176,0.18)_0%,transparent_60%)] blur-2xl" />
          <div className="pointer-events-none absolute -left-24 bottom-0 size-72 rounded-full bg-[radial-gradient(50%_50%_at_50%_50%,rgba(124,58,237,0.16)_0%,transparent_60%)] blur-2xl" />
        </div>
      </Container>
    </Section>
  )
}


