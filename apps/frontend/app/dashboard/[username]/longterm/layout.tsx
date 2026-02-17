import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Long Term Trading",
}

export default function LongTermLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return children
}
