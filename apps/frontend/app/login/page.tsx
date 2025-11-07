"use client"

import Image from "next/image"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useForm } from "react-hook-form"
import { Button } from "@/components/ui/button"
import { useState } from "react"
import { login as loginRequest } from "@/lib/auth"

type LoginFormValues = {
	email: string
	password: string
	organizationId?: string
}

export default function LoginPage() {
	const router = useRouter()
	const {
		register,
		handleSubmit,
		formState: { errors },
	} = useForm<LoginFormValues>({
		defaultValues: { email: "", password: "", organizationId: "" },
	})
	const [submitting, setSubmitting] = useState(false)
	const [apiError, setApiError] = useState<string | null>(null)

	async function onSubmit(values: LoginFormValues) {
		setApiError(null)
		setSubmitting(true)
		try {
			const response = await loginRequest({
				email: values.email,
				password: values.password,
				organization_id: values.organizationId?.trim() || undefined,
			})

			const { access_token, refresh_token, user } = response.data

			if (typeof window !== "undefined") {
				localStorage.setItem("access_token", access_token)
				localStorage.setItem("refresh_token", refresh_token)
				localStorage.setItem("user_id", user.id)
				localStorage.setItem("organization_id", user.organization_id)
			}

			router.push("/admin")
		} catch (error) {
			setApiError(error instanceof Error ? error.message : "Login failed")
		} finally {
			setSubmitting(false)
		}
	}

return (
	<main className="relative min-h-screen overflow-y-auto">
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
		<div className="absolute inset-y-0 right-0 z-10 flex w-full justify-center overflow-y-auto bg-black py-16 md:w-1/2 md:py-20">
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
			<div className="w-full max-w-md px-6 text-white">
					<h1 className="mb-8 text-center text-4xl font-semibold tracking-wide">
						Log in to AlphaPilot
					</h1>

					{apiError && (
						<div className="mb-4 rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
							{apiError}
						</div>
					)}
					<form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
						<div className="space-y-2">
							<label className="block text-sm font-medium text-zinc-200">Email</label>
							<input
								{...register("email", { required: "Email is required" })}
								type="email"
								placeholder="you@company.com"
								className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/50 outline-none ring-0 focus:border-white/25"
							/>
							{errors.email && <p className="text-sm text-rose-300">{errors.email.message}</p>}
						</div>

						<div className="space-y-2">
							<label className="block text-sm font-medium text-zinc-200">Password</label>
							<input
								{...register("password", { required: "Password is required" })}
								type="password"
								placeholder="Your password"
								className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/50 outline-none ring-0 focus:border-white/25"
							/>
							{errors.password && <p className="text-sm text-rose-300">{errors.password.message}</p>}
						</div>

						<div className="space-y-2">
							<label className="block text-sm font-medium text-zinc-200">Organization ID (optional)</label>
							<input
								{...register("organizationId")}
								placeholder="0eb89373-75d4-4016-ba0b-1194a9234fbf"
								className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/50 outline-none ring-0 focus:border-white/25"
							/>
						</div>

						<div className="pt-4">
							<Button
								type="submit"
								variant="outline"
								disabled={submitting}
								className="h-11 w-full cursor-pointer rounded-xl border-white/90 text-lg text-white hover:bg-white/60 font-playfair disabled:cursor-not-allowed disabled:opacity-60"
							>
								{submitting ? "Logging in..." : "Login"}
							</Button>
						</div>
					</form>
					<div className="mt-4 text-center text-sm text-white/80">
						Don&apos;t have an account?{" "}
						<Link href="/signup" className="underline hover:text-white">
							Register here.
						</Link>
					</div>
				</div>
			</div>

			{/* Spacer to preserve layout height when absolute children are used */}
			<div className="invisible h-svh md:visible md:h-svh" />
		</main>
	)
}
