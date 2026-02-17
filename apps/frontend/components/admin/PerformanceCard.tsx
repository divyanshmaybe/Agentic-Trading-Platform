import type { ComponentProps, ComponentPropsWithoutRef } from "react";
import { Line } from "react-chartjs-2";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type LineChartConfig = Pick<ComponentProps<typeof Line>, "data" | "options" | "plugins">;

type PerformanceCardProps = {
  title?: string;
  chart: LineChartConfig;
  className?: string;
} & ComponentPropsWithoutRef<typeof Card>;

export function PerformanceCard({ title = "Performance", chart, className = "", ...cardProps }: PerformanceCardProps) {
  return (
    <Card
      className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur flex h-full flex-col sm:col-span-2 lg:col-span-12 ${className}`}
      {...cardProps}
    >
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[360px] w-full rounded-xl border border-white/10 bg-black/20 p-2">
          <Line data={chart.data} options={chart.options} plugins={chart.plugins} />
        </div>
      </CardContent>
    </Card>
  );
}

