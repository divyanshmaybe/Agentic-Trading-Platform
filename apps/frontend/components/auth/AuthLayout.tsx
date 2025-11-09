import Image from "next/image"
import Link from "next/link"
import { ReactNode } from "react"

import { ArrowLeft } from "lucide-react"

import { Button } from "@/components/ui/button"

type AuthLayoutProps = {
	title: string
	backLink: { href: string; label: string }
	children: ReactNode
	subtitle?: string
	footer?: ReactNode
}

export function AuthLayout({ title, subtitle, backLink, children, footer }: AuthLayoutProps) {
	const backButton = (
		<Button
			asChild
			variant="outline"
			size="icon"
			className="border-white/70 text-white hover:bg-white/20"
		>
			<Link href={backLink.href}>
				<ArrowLeft className="h-5 w-5" />
				<span className="sr-only">{backLink.label}</span>
			</Link>
		</Button>
	)

	return (
		<main className="relative min-h-screen overflow-y-auto no-scrollbar">
			<div className="absolute inset-0">
				<Image src="/images/hero-bg.jpg" alt="Background" fill priority className="object-cover" />
			</div>
			<div className="absolute inset-y-0 right-0 z-10 flex w-full justify-center overflow-y-auto bg-black py-16 no-scrollbar md:w-1/2 md:py-20">
				<div className="w-full max-w-md px-4 text-white sm:pt-16">
					<div className="mb-8 flex justify-end sm:mb-10">{backButton}</div>
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


