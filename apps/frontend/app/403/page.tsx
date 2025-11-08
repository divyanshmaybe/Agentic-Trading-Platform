"use client"

import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Container } from "@/components/shared/Container"

export default function ForbiddenPage() {
  return (
    <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa] flex items-center justify-center">
      <Container className="max-w-2xl text-center">
        <h1 className="text-6xl font-bold mb-4">403</h1>
        <h2 className="text-3xl font-semibold mb-4">Access Forbidden</h2>
        <p className="text-lg text-white/60 mb-8">
          You don't have permission to access this page.
        </p>
        <div className="flex gap-4 justify-center">
          <Button
            asChild
            variant="outline"
            className="border-white/15 bg-black/40 px-6 py-2 text-white hover:bg-black/60"
          >
            <Link href="/">Go Home</Link>
          </Button>
          <Button
            asChild
            variant="outline"
            className="border-white/15 bg-black/40 px-6 py-2 text-white hover:bg-black/60"
          >
            <Link href="/login">Login</Link>
          </Button>
        </div>
      </Container>
    </div>
  )
}

