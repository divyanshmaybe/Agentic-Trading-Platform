"use client"

import { useEffect, useMemo, useRef, useState } from "react";
import { Line } from "react-chartjs-2";
import { Container } from "@/components/shared/Container";
import { Section, SectionHeader } from "@/components/shared/Section";
import "@/lib/chart"; // registers chart.js once

const MAX_POINTS = 60;

function generateNext(prev: number): number {
  const drift = 0.02; // gentle upward bias
  const noise = (Math.random() - 0.5) * 0.6; // volatility
  const next = Math.max(0, prev + drift + noise);
  return Number(next.toFixed(2));
}

export function PerformanceChart() {
  const [series, setSeries] = useState<number[]>(() => Array.from({ length: 20 }, (_, i) => 100 + i * 0.2));
  const [labels, setLabels] = useState<string[]>(() => Array.from({ length: 20 }, (_, i) => `${i - 19}m`));
  const last = useRef(series[series.length - 1] ?? 100);

  useEffect(() => {
    const id = setInterval(() => {
      last.current = generateNext(last.current);
      setSeries((prev) => {
        const next = [...prev, last.current];
        return next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next;
      });
      setLabels((prev) => {
        const next = [...prev, `${prev.length - 19}m`];
        return next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next;
      });
    }, 1200);
    return () => clearInterval(id);
  }, []);

  const data = useMemo(
    () => ({
      labels,
      datasets: [
        {
          label: "Simulated NAV",
          data: series,
          borderColor: "#60A5FA",
          backgroundColor: "rgba(96,165,250,0.2)",
          fill: true,
          pointRadius: 0,
          borderWidth: 2,
          tension: 0.35,
        },
      ],
    }),
    [labels, series]
  );

  const options = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { mode: "index" as const, intersect: false },
      },
      scales: {
        x: {
          ticks: { color: "#94a3b8" },
          grid: { display: false },
        },
        y: {
          ticks: { color: "#94a3b8" },
          grid: { color: "rgba(148,163,184,0.15)" },
        },
      },
      interaction: { intersect: false, mode: "nearest" as const },
      animation: { duration: 500 },
    }),
    []
  );

  return (
    <Section id="performance">
      <Container>
        <SectionHeader
          eyebrow="Visualization"
          title="Performance that learns and evolves"
          subtitle="A living signal that adapts to changing market regimes."
        />
        <div className="mt-8 h-72 w-full overflow-hidden rounded-xl border bg-card">
          <Line data={data} options={options} height={288} />
        </div>
      </Container>
    </Section>
  );
}
