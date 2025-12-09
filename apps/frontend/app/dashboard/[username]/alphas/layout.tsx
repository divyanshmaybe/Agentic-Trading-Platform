import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Alpha Strategies",
}

export default function AlphasLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return children
}
