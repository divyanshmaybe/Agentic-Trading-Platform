"use client"

import Image from "next/image"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useForm } from "react-hook-form"
import { Button } from "@/components/ui/button"
import { useState } from "react"
import { registerOrganization } from "@/lib/auth"

type SignupFormValues = {
	companyName: string
	companyEmail: string
	phone?: string
	address?: string
	registrationNumber?: string
	taxId?: string
	adminFirstName: string
	adminLastName: string
	adminEmail: string
	adminPassword: string
	confirmPassword: string
}

export default function SignupPage() {
	const router = useRouter()
	const {
		register,
		handleSubmit,
		setError,
		reset,
		formState: { errors },
	} = useForm<SignupFormValues>({
		defaultValues: {
			companyName: "",
			companyEmail: "",
			phone: "",
			address: "",
			registrationNumber: "",
			taxId: "",
			adminFirstName: "",
			adminLastName: "",
			adminEmail: "",
			adminPassword: "",
			confirmPassword: "",
		},
	})
	const [submitting, setSubmitting] = useState(false)
	const [apiError, setApiError] = useState<string | null>(null)
	const [successMessage, setSuccessMessage] = useState<string | null>(null)

	async function onSubmit(values: SignupFormValues) {
		setApiError(null)
		setSuccessMessage(null)

		if (values.adminPassword !== values.confirmPassword) {
			setError("confirmPassword", { type: "validate", message: "Passwords do not match" })
			return
		}

		setSubmitting(true)
		try {
			const response = await registerOrganization({
				name: values.companyName,
				email: values.companyEmail,
				phone: values.phone?.trim() || undefined,
				address: values.address?.trim() || undefined,
				registration_number: values.registrationNumber?.trim() || undefined,
				tax_id: values.taxId?.trim() || undefined,
				admin: {
					email: values.adminEmail,
					password: values.adminPassword,
					first_name: values.adminFirstName,
					last_name: values.adminLastName,
				},
			})

			const { access_token, refresh_token, organization } = response.data

			if (typeof window !== "undefined") {
				localStorage.setItem("access_token", access_token)
				localStorage.setItem("refresh_token", refresh_token)
				localStorage.setItem("organization_id", organization.id)
			}

			setSuccessMessage("Organization registered successfully. Redirecting...")
			reset()
			setTimeout(() => {
				router.push("/login")
			}, 1500)
		} catch (error) {
			setApiError(error instanceof Error ? error.message : "Failed to register organization")
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
			<div className="w-full max-w-md px-6 text-white">
					<h1 className="mb-8 text-center text-4xl font-semibold tracking-wide">
						Register Organization
					</h1>

					{apiError && (
						<div className="mb-4 rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
							{apiError}
						</div>
					)}
					{successMessage && (
						<div className="mb-4 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
							{successMessage}
						</div>
					)}
					<form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
						<div className="grid grid-cols-1 gap-5">
							<div className="space-y-2">
								<label className="block text-sm font-medium text-zinc-200">Company Name</label>
								<input
									{...register("companyName", { required: "Company name is required" })}
									placeholder="Acme Corporation"
									className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/40 outline-none ring-0 focus:border-white/25"
								/>
								{errors.companyName && <p className="text-sm text-rose-300">{errors.companyName.message}</p>}
							</div>

							<div className="space-y-2">
								<label className="block text-sm font-medium text-zinc-200">Company Email</label>
								<input
									{...register("companyEmail", { required: "Company email is required" })}
									type="email"
									placeholder="contact@acme.com"
									className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/40 outline-none ring-0 focus:border-white/25"
								/>
								{errors.companyEmail && <p className="text-sm text-rose-300">{errors.companyEmail.message}</p>}
							</div>

							<div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
								<div className="space-y-2">
									<label className="block text-sm font-medium text-zinc-200">Phone</label>
									<input
										{...register("phone")}
										placeholder="+91 12345 67890"
										className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/40 outline-none ring-0 focus:border-white/25"
									/>
								</div>
								<div className="space-y-2">
									<label className="block text-sm font-medium text-zinc-200">Registration Number</label>
									<input
										{...register("registrationNumber")}
										placeholder="REG123456"
										className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/40 outline-none ring-0 focus:border-white/25"
									/>
								</div>
							</div>

							<div className="space-y-2">
								<label className="block text-sm font-medium text-zinc-200">Company Address</label>
								<textarea
									{...register("address")}
									placeholder="123 Business Street, Mumbai, India"
									rows={2}
									className="w-full resize-none rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/40 outline-none ring-0 focus:border-white/25"
								/>
							</div>

							<div className="space-y-2">
								<label className="block text-sm font-medium text-zinc-200">Tax ID</label>
								<input
									{...register("taxId")}
									placeholder="TAX987654"
									className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/40 outline-none ring-0 focus:border-white/25"
								/>
							</div>

							<div className="border-t border-white/10 pt-5">
								<h2 className="text-lg font-semibold text-white">Admin Details</h2>
							</div>

							<div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
								<div className="space-y-2">
									<label className="block text-sm font-medium text-zinc-200">First Name</label>
									<input
										{...register("adminFirstName", { required: "First name is required" })}
										placeholder="John"
										className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/40 outline-none ring-0 focus:border-white/25"
									/>
									{errors.adminFirstName && <p className="text-sm text-rose-300">{errors.adminFirstName.message}</p>}
								</div>
								<div className="space-y-2">
									<label className="block text-sm font-medium text-zinc-200">Last Name</label>
									<input
										{...register("adminLastName", { required: "Last name is required" })}
										placeholder="Doe"
										className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/40 outline-none ring-0 focus:border-white/25"
									/>
									{errors.adminLastName && <p className="text-sm text-rose-300">{errors.adminLastName.message}</p>}
								</div>
							</div>

							<div className="space-y-2">
								<label className="block text-sm font-medium text-zinc-200">Admin Email</label>
								<input
									{...register("adminEmail", { required: "Admin email is required" })}
									type="email"
									placeholder="admin@acme.com"
									className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/40 outline-none ring-0 focus:border-white/25"
								/>
								{errors.adminEmail && <p className="text-sm text-rose-300">{errors.adminEmail.message}</p>}
							</div>

							<div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
								<div className="space-y-2">
									<label className="block text-sm font-medium text-zinc-200">Admin Password</label>
									<input
										{...register("adminPassword", { required: "Password is required", minLength: { value: 8, message: "Use at least 8 characters" } })}
										type="password"
										placeholder="SecurePass123!"
										className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/40 outline-none ring-0 focus:border-white/25"
									/>
									{errors.adminPassword && <p className="text-sm text-rose-300">{errors.adminPassword.message}</p>}
								</div>
								<div className="space-y-2">
									<label className="block text-sm font-medium text-zinc-200">Confirm Password</label>
									<input
										{...register("confirmPassword", { required: "Confirm your password" })}
										type="password"
										placeholder="Confirm password"
										className="w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/40 outline-none ring-0 focus:border-white/25"
									/>
									{errors.confirmPassword && <p className="text-sm text-rose-300">{errors.confirmPassword.message}</p>}
								</div>
							</div>
						</div>

						<div className="pt-4">
							<Button
								type="submit"
								variant="outline"
								disabled={submitting}
								className="h-11 w-full cursor-pointer rounded-xl border-white/90 text-lg text-white hover:bg-white/60 font-playfair disabled:cursor-not-allowed disabled:opacity-60"
							>
								{submitting ? "Registering..." : "Sign Up"}
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


