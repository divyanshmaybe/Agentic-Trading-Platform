import data from "@/data/dashboard.mock.json";

export type Investor = {
  id: string;
  name: string;
  value: number;
  growthPct: number;
  series: number[];
  role?: "Viewer" | "Editor" | "Admin";
  active?: boolean;
};

export type DashboardData = {
  months: string[];
  companyTotals: number[];
  investors: Investor[];
};

export function getDashboardData(): DashboardData {
  // Clone to avoid accidental mutation from consumers
  const investorsWithDefaults = data.investors.map((inv) => ({
    role: "Viewer" as const,
    active: true,
    ...inv,
  }));
  return {
    months: [...data.months],
    companyTotals: [...data.companyTotals],
    investors: investorsWithDefaults,
  };
}

export function getTopKInvestors(investors: Investor[], k = 3): Investor[] {
  return [...investors].sort((a, b) => b.value - a.value).slice(0, k);
}

export function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
}

export function computeRoiPct(series: number[]): number {
  if (series.length < 2) return 0;
  const first = series[0];
  const last = series[series.length - 1];
  if (first === 0) return 0;
  return ((last - first) / first) * 100;
}


