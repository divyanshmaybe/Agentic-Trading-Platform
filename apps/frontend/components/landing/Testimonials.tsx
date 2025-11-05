"use client"

import { motion, useAnimationFrame } from "framer-motion";
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
  const baseX = useRef(0);
  useAnimationFrame((t, delta) => {
    const direction = reverse ? -1 : 1;
    baseX.current += direction * (delta / 16) * 0.25; // speed
  });

  return (
    <div className="relative overflow-hidden">
      <motion.div
        className="flex min-w-max gap-6"
        style={{ x: baseX.current % 400 }}
      >
        {[...TESTIMONIALS, ...TESTIMONIALS].map((t, i) => (
          <figure
            key={i}
            className="w-[320px] shrink-0 rounded-xl border bg-card p-5 shadow-sm"
          >
            <blockquote className="text-sm leading-relaxed">“{t.quote}”</blockquote>
            <figcaption className="mt-3 text-xs text-muted-foreground">{t.author}</figcaption>
          </figure>
        ))}
      </motion.div>
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
