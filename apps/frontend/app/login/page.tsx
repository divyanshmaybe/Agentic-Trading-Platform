"use client"

import Image from "next/image"
import Link from "next/link"
import { useForm } from "react-hook-form"
import { Button } from "@/components/ui/button"
import React from "react"

type LoginFormValues = {
	company: string
	username: string
	password: string
}

export default function LoginPage() {
	const { register, handleSubmit } = useForm<LoginFormValues>({
		defaultValues: { company: "", username: "", password: "" },
	})

	function onSubmit(_values: LoginFormValues) {
		// no-op for now (no backend integration yet)
	}

	return (
		<main className="relative min-h-[100svh] overflow-hidden">
			{/* Full-viewport background image */}
			<div className="absolute inset-0">
				<Image
					src="/images/hero-bg.jpg"
					alt="Background"
					fill
					priority
					className="object-cover"
				/>
			</div>

			{/* Right-half black overlay (full on mobile) */}
			<div className="absolute inset-y-0 right-0 z-10 flex w-full items-center justify-center bg-black md:w-1/2">
				{/* Back to Home button (top-right, inside overlay) */}
				<div className="absolute right-8 top-6">
					<Button
						asChild
						variant="outline"
						size="lg"
						className="border-white/70 text-white hover:bg-white/20"
					>
						<Link href="/">Back to Home</Link>
					</Button>
				</div>
				<div className="w-full max-w-md p-6 text-white">
					<h1 className="mb-8 text-center text-4xl font-semibold tracking-wide">
						AlphaPilot
					</h1>

					<form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
						<div className="space-y-2">
							<label className="block text-sm font-medium text-zinc-200">Company</label>
							<input
								{...register("company")}
								placeholder="Company"
								className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/50 outline-none ring-0 focus:border-white/25"
							/>
						</div>

						<div className="space-y-2">
							<label className="block text-sm font-medium text-zinc-200">Username</label>
							<input
								{...register("username")}
								placeholder="Username"
								className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/50 outline-none ring-0 focus:border-white/25"
							/>
						</div>

						<div className="space-y-2">
							<label className="block text-sm font-medium text-zinc-200">Password</label>
							<input
								{...register("password")}
								type="password"
								placeholder="Password"
								className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/50 outline-none ring-0 focus:border-white/25"
							/>
						</div>

						<div className="pt-4">
							<Button
								type="button"
								variant="outline"
								className="h-11 w-full rounded-xl text-lg border-white/90 text-white hover:bg-white/60 cursor-pointer font-playfair"
							>
								Login
							</Button>
						</div>
					</form>
				</div>
			</div>

			{/* Spacer to preserve layout height when absolute children are used */}
			<div className="invisible h-[100svh] md:visible md:h-[100svh]" />
		</main>
	)
}


