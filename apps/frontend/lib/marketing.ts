export const brand = {
  name: "AgentInvest",
  blue: "#2563EB",
  blueHover: "#1D4ED8",
};

export const nav = [
  { label: "Features", href: "#features" },
  { label: "Performance", href: "#performance" },
  { label: "Testimonials", href: "#testimonials" },
  { label: "Pricing", href: "#pricing" },
];

export const hero = {
  title: "Meet Your AI Portfolio Manager.",
  description:
    "An agentic AI that trades intelligently across high-risk and low-risk markets — 24/7 performance, zero emotion.",
  primaryCta: { label: "Get Started", href: "#cta" },
};

export type Feature = {
  icon: "LineChart" | "ShieldCheck" | "Zap" | "Brain" | "BarChart3" | "Lock";
  title: string;
  description: string;
};

export const features: Feature[] = [
  {
    icon: "Brain",
    title: "Agentic Intelligence",
    description:
      "Autonomously makes trading decisions with continuous feedback loops.",
  },
  {
    icon: "ShieldCheck",
    title: "Risk Adaptive",
    description:
      "Balances volatile and stable assets based on real-time risk.",
  },
  {
    icon: "Zap",
    title: "Real-Time Insights",
    description:
      "Monitoring, sentiment analysis, and alerts without noise.",
  },
  {
    icon: "LineChart",
    title: "Transparent Performance",
    description:
      "Audit every AI decision with clear rationales and traces.",
  },
];

export const steps = [
  {
    number: 1,
    title: "Connect and normalize",
    description:
      "Link custodians and brokers. We normalize holdings, transactions, and prices.",
  },
  {
    number: 2,
    title: "Set mandates",
    description:
      "Define objectives, constraints, and guardrails per strategy and account group.",
  },
  {
    number: 3,
    title: "Automate and approve",
    description:
      "Agents rebalance continuously; you approve, throttle, or override as needed.",
  },
];

export const kpis = [
  { value: "$12B+", label: "AUM analyzed" },
  { value: "1.2M", label: "Signals/day" },
  { value: "99.99%", label: "Uptime SLA" },
  { value: "<120ms", label: "Median inference" },
];

export const faqs = [
  {
    q: "How does Pathway Finance fit into my stack?",
    a: "We connect to brokers/custodians for execution and your data warehouse for analytics. You control approval and policy.",
  },
  {
    q: "Is it safe to automate rebalancing?",
    a: "Agents operate within explicit mandates. Every decision includes validation and an audit trail, with human-in-the-loop by default.",
  },
  {
    q: "What does integration look like?",
    a: "Start with read-only connectors, then enable paper trading. Move to production after mandate sign-off and sandbox burn-in.",
  },
  {
    q: "Data residency & compliance?",
    a: "Deployed in your region with encryption at rest and in transit. We support data minimization and configurable retention.",
  },
];


