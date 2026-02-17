import type { ComponentPropsWithoutRef } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type StatMetric = {
  label: string;
  value: string;
  valueClassName?: string;
  title?: string;
};

type FinancialStatsCardProps = {
  title?: string;
  metrics: StatMetric[];
  savedAt?: number | null;
  className?: string;
} & ComponentPropsWithoutRef<typeof Card>;

export function FinancialStatsCard({ title = "Key Financial Stats", metrics, savedAt, className = "", ...cardProps }: FinancialStatsCardProps) {
  const lastSavedLabel = savedAt ? `Last saved ${new Date(savedAt).toLocaleTimeString()}` : "\u00A0";

  return (
    <Card
      className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur flex h-full flex-col sm:col-span-1 lg:col-span-6 ${className}`}
      {...cardProps}
    >
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex-1">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {metrics.map((metric) => (
            <Stat key={metric.label} {...metric} />
          ))}
        </div>
        <div className="mt-2 text-xs text-white/60">{lastSavedLabel}</div>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, valueClassName, title }: StatMetric) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4" title={title}>
      <div className="text-xs text-white/60">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${valueClassName ?? ""}`}>{value}</div>
    </div>
  );
}

