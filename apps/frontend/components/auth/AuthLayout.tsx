import Image from "next/image"
import Link from "next/link"
import { ReactNode } from "react"

import { Button } from "@/components/ui/button"

type AuthLayoutProps = {
	title: string
	backLink: { href: string; label: string }
	children: ReactNode
	subtitle?: string
	footer?: ReactNode
}

export function AuthLayout({ title, subtitle, backLink, children, footer }: AuthLayoutProps) {
	return (
		<main className="relative min-h-screen overflow-y-auto">
			<div className="absolute inset-0">
				<Image src="/images/hero-bg.jpg" alt="Background" fill priority className="object-cover" />
			</div>
			<div className="absolute inset-y-0 right-0 z-10 flex w-full justify-center overflow-y-auto bg-black py-16 md:w-1/2 md:py-20">
				<div className="absolute right-8 top-6">
					<Button asChild variant="outline" size="lg" className="border-white/70 text-white hover:bg-white/20">
						<Link href={backLink.href}>{backLink.label}</Link>
					</Button>
				</div>
				<div className="w-full max-w-md px-6 text-white">
					<h1 className="mb-3 text-center text-4xl font-semibold tracking-wide">{title}</h1>
					{subtitle ? <p className="mb-6 text-center text-sm text-white/70">{subtitle}</p> : null}
					{children}
					{footer ? <div className="mt-4 text-center text-sm text-white/80">{footer}</div> : null}
				</div>
			</div>
			<div className="invisible h-svh md:visible md:h-svh" />
		</main>
	)
}


