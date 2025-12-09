import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Objectives",
}

export default function ObjectivesLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return children
}
