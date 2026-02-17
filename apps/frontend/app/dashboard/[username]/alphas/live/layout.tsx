import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Live Alphas",
}

export default function LiveAlphasLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return children
}
