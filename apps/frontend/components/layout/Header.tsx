"use client"
import Link from "next/link"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Container } from "@/components/shared/Container"
import { brand, nav } from "@/lib/marketing"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export function Header() {
  return (
    <header className="fixed inset-x-0 top-0 z-50 w-full bg-white/20 backdrop-blur-md backdrop-saturate-100 dark:bg-white/15">
      <Container className="flex h-16 items-center justify-between text-primary-foreground">
        <Link href="#" className="flex items-center gap-2 font-semibold">
          <span className={cn("text-3xl font-playfair")}>{brand.name}</span>
        </Link>
        <nav className="hidden items-center gap-6 text-lg font-playfair font-medium md:flex">
          {nav.map((item) => (
            <Link key={item.href} href={item.href} className="text-primary-foreground/90 hover:text-primary-foreground">
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="hidden items-center gap-3 md:flex">
        	<Button asChild className="bg-(--brand-navy) text-white hover:opacity-90">
            <Link href="/login">Get Started</Link>
			</Button>		
        </div>
        <div className="flex items-center gap-2 md:hidden">
          <Button asChild size="sm" className="bg-(--brand-navy) text-white hover:opacity-90">
            <Link href="/login">Get Started</Link>
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon" aria-label="Open menu" className="text-primary-foreground border-white/40">
                ☰
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {nav.map((item) => (
                <DropdownMenuItem key={item.href} asChild>
                  <Link href={item.href}>{item.label}</Link>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </Container>
    </header>
  )
}


