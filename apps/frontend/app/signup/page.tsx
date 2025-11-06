"use client"

import Image from "next/image"
import Link from "next/link"
import { useForm } from "react-hook-form"
import { Button } from "@/components/ui/button"
import React from "react"

type SignupFormValues = {
	companyName: string
	adminUsername: string
	adminPassword: string
	confirmPassword: string
}

export default function SignupPage() {
	const { register, handleSubmit } = useForm<SignupFormValues>({
		defaultValues: {
			companyName: "",
			adminUsername: "",
			adminPassword: "",
			confirmPassword: "",
		},
	})

	function onSubmit(_values: SignupFormValues) {
		// no-op for now (no backend integration yet)
	}

	return (
		<main className="relative min-h-svh overflow-hidden">
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
				{/* Back to Login button (top-right, inside overlay) */}
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
						Register Organization
					</h1>

					<form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
						<div className="space-y-2">
							<label className="block text-sm font-medium text-zinc-200">Company Name</label>
							<input
								{...register("companyName")}
								placeholder="Company Name"
								className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/50 outline-none ring-0 focus:border-white/25"
							/>
						</div>

						<div className="space-y-2">
							<label className="block text-sm font-medium text-zinc-200">Admin Username</label>
							<input
								{...register("adminUsername")}
								placeholder="Admin Username"
								className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/50 outline-none ring-0 focus:border-white/25"
							/>
						</div>

						<div className="space-y-2">
							<label className="block text-sm font-medium text-zinc-200">Admin Password</label>
							<input
								{...register("adminPassword")}
								type="password"
								placeholder="Admin Password"
								className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/50 outline-none ring-0 focus:border-white/25"
							/>
						</div>

						<div className="space-y-2">
							<label className="block text-sm font-medium text-zinc-200">Confirm Password</label>
							<input
								{...register("confirmPassword")}
								type="password"
								placeholder="Confirm Password"
								className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/50 outline-none ring-0 focus:border-white/25"
							/>
						</div>

						<div className="pt-4">
							<Button
								type="button"
								variant="outline"
								className="h-11 w-full rounded-xl text-lg border-white/90 text-white hover:bg-white/60 cursor-pointer font-playfair"
							>
								Sign Up
							</Button>
						</div>
					</form>
					<div className="mt-4 text-center text-sm text-white/80">
						Already have an account?{" "}
						<Link href="/login" className="underline hover:text-white">
							Login here.
						</Link>
					</div>
				</div>
			</div>

			{/* Spacer to preserve layout height when absolute children are used */}
			<div className="invisible h-svh md:visible md:h-svh" />
		</main>
	)
}


