import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Access Forbidden",
}

export default function ForbiddenLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return children
}
