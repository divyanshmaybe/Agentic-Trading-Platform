"use client"

import { useRouter } from "next/navigation"
import { useForm } from "react-hook-form"
import { useState } from "react"
import Link from "next/link"
import { login as loginRequest } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { AuthField, AuthLayout, AuthNotice, authInputClassName } from "@/components/auth"

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
			// SECURITY: Only store tokens in cookies (httpOnly for refresh, regular for access)
			// DO NOT store user role, username, or any auth data in localStorage - it can be manipulated!
			document.cookie = `access_token=${access_token}; path=/; max-age=${7 * 24 * 60 * 60}; SameSite=Lax`
			
			// Store non-sensitive display data only (for UI convenience, NOT security)
			localStorage.setItem("user_first_name", user.first_name)
			localStorage.setItem("user_id", user.id) // Only for API calls, NOT authorization
		}

		if (user.role === "admin") {
			router.push("/admin")
		} else {
			router.push(`/dashboard/${user.username}`)
		}
		} catch (error) {
			setApiError(error instanceof Error ? error.message : "Login failed")
		} finally {
			setSubmitting(false)
		}
	}

	return (
		<AuthLayout
			title="Log in to AgentInvest"
			backLink={{ href: "/", label: "Back to Home" }}
			footer={
				<>
					Don&apos;t have an account?{" "}
					<Link href="/signup" className="underline hover:text-white">
						Register here.
					</Link>
				</>
			}
		>
			{apiError ? <AuthNotice variant="error" message={apiError} /> : null}
			<form onSubmit={handleSubmit(onSubmit)} className="space-y-5 no-scrollbar">
				<AuthField label="Email" error={errors.email?.message}>
					<input
						{...register("email", { required: "Email is required" })}
						type="email"
						placeholder="you@company.com"
						className={authInputClassName}
					/>
				</AuthField>
				<AuthField label="Password" error={errors.password?.message}>
					<input
						{...register("password", { required: "Password is required" })}
						type="password"
						placeholder="Your password"
						className={authInputClassName}
					/>
				</AuthField>
				<AuthField label="Organization ID (optional)">
					<input
						{...register("organizationId")}
						placeholder="0eb89373-75d4-4016-ba0b-1194a9234fbf"
						className={authInputClassName}
					/>
				</AuthField>
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
		</AuthLayout>
	)
}
