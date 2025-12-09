import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Intraday Trading",
}

export default function IntradayLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return children
}
