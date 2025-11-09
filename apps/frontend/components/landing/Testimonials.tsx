"use client"

import { useAnimationFrame } from "framer-motion";
import { useRef } from "react";
import { Container } from "@/components/shared/Container";
import { Section, SectionHeader } from "@/components/shared/Section";

const TESTIMONIALS = [
  {
    quote:
      "Pathway lets us automate rebalancing confidently. The agent explains every move.",
    author: "VP Portfolio Strategy, TechFin",
  },
  {
    quote:
      "Our risk exposure stays in bounds, even in volatile sessions. Huge unlock.",
    author: "Head of Trading, Investly",
  },
  { quote: "Best execution quality we've seen on small-team infra.", author: "CIO, AlgoWave" },
  { quote: "Fast setup, clear analytics, and strong governance.", author: "PM, QuantEdge" },
];

function MarqueeRow({ reverse = false }: { reverse?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const directionRef = useRef(reverse ? -1 : 1);

  useAnimationFrame((_, delta) => {
    const container = containerRef.current;
    if (!container) return;

    const maxScroll = container.scrollWidth - container.clientWidth;
    if (maxScroll <= 0) return;

    const speed = (delta / 16) * 0.5; // speed
    container.scrollLeft += directionRef.current * speed;

    if (container.scrollLeft <= 0) {
      container.scrollLeft = 0;
      directionRef.current = 1;
    } else if (container.scrollLeft >= maxScroll) {
      container.scrollLeft = maxScroll;
      directionRef.current = -1;
    }
  });

  return (
    <div ref={containerRef} className="relative overflow-x-auto no-scrollbar md:overflow-hidden">
      <div className="flex min-w-max gap-6 px-1 md:px-0">
        {TESTIMONIALS.map((t, i) => (
          <figure
            key={i}
            className="w-[320px] shrink-0 rounded-xl border bg-card p-5 shadow-sm"
          >
            <blockquote className="text-sm leading-relaxed">“{t.quote}”</blockquote>
            <figcaption className="mt-3 text-xs text-muted-foreground">{t.author}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}

export function Testimonials() {
  return (
    <Section id="testimonials">
      <Container>
        <SectionHeader
          eyebrow="Social proof"
          title="Trusted by forward-looking teams"
          subtitle="Designed for professionals who demand clarity and control."
        />
        <div className="mt-8 space-y-6">
          <MarqueeRow />
          <MarqueeRow reverse />
        </div>
      </Container>
    </Section>
  );
}
