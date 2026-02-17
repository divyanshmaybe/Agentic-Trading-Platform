"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { useForm, RegisterOptions } from "react-hook-form"
import { AuthField, AuthLayout, AuthNotice, authInputClassName } from "@/components/auth"
import { Button } from "@/components/ui/button"
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

type FieldConfig<K extends keyof SignupFormValues> = {
	name: K
	label: string
	placeholder: string
	type?: string
	rules?: RegisterOptions<SignupFormValues, K>
}

const companyFields: FieldConfig<"companyName" | "companyEmail">[] = [
	{
		name: "companyName",
		label: "Company Name",
		placeholder: "Acme Corporation",
		rules: { required: "Company name is required" },
	},
	{
		name: "companyEmail",
		label: "Company Email",
		placeholder: "contact@acme.com",
		type: "email",
		rules: { required: "Company email is required" },
	},
]

const optionalCompanyFields: FieldConfig<"phone" | "registrationNumber" | "address" | "taxId">[] = [
	{ name: "phone", label: "Phone", placeholder: "+91 12345 67890" },
	{ name: "registrationNumber", label: "Registration Number", placeholder: "REG123456" },
	{
		name: "address",
		label: "Company Address",
		placeholder: "123 Business Street, Mumbai, India",
	},
	{ name: "taxId", label: "Tax ID", placeholder: "TAX987654" },
]

const [phoneField, registrationField, addressField, taxField] = optionalCompanyFields

const adminFields: FieldConfig<
	"adminFirstName" | "adminLastName" | "adminEmail" | "adminPassword" | "confirmPassword"
>[] = [
	{
		name: "adminFirstName",
		label: "First Name",
		placeholder: "John",
		rules: { required: "First name is required" },
	},
	{
		name: "adminLastName",
		label: "Last Name",
		placeholder: "Doe",
		rules: { required: "Last name is required" },
	},
	{
		name: "adminEmail",
		label: "Admin Email",
		placeholder: "admin@acme.com",
		type: "email",
		rules: { required: "Admin email is required" },
	},
	{
		name: "adminPassword",
		label: "Admin Password",
		placeholder: "SecurePass123!",
		type: "password",
		rules: {
			required: "Password is required",
			minLength: { value: 8, message: "Use at least 8 characters" },
		},
	},
	{
		name: "confirmPassword",
		label: "Confirm Password",
		placeholder: "Confirm password",
		type: "password",
		rules: { required: "Confirm your password" },
	},
]

const [adminFirstNameField, adminLastNameField, adminEmailField, adminPasswordField, confirmPasswordField] = adminFields

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

		const { access_token, refresh_token, organization, user } = response.data

		if (typeof window !== "undefined") {
			// SECURITY: Only store tokens in cookies (httpOnly for refresh, regular for access)
			// DO NOT store user role, username, or any auth data in localStorage - it can be manipulated!
			document.cookie = `access_token=${access_token}; path=/; max-age=${7 * 24 * 60 * 60}; SameSite=Lax`
			
			// Store non-sensitive display data only (for UI convenience, NOT security)
			localStorage.setItem("user_first_name", user.first_name)
			localStorage.setItem("user_id", user.id) // Only for API calls, NOT authorization
		}

		setSuccessMessage("Organization registered successfully. Redirecting...")
		reset()
		setTimeout(() => {
			router.push(`/dashboard/${user.username}`)
		}, 1500)
		} catch (error) {
			setApiError(error instanceof Error ? error.message : "Failed to register organization")
		} finally {
			setSubmitting(false)
		}
	}

	return (
		<AuthLayout
			title="Register Organization"
			subtitle="Create an organization account and onboard your admin in one step."
			backLink={{ href: "/", label: "Back to Home" }}
			footer={
				<div className="pb-8">
					Already have an account?{" "}
					<Link href="/login" className="underline hover:text-white">
						Login here.
					</Link>
				</div>
			}
		>
			{apiError ? <AuthNotice variant="error" message={apiError} /> : null}
			{successMessage ? <AuthNotice variant="success" message={successMessage} /> : null}
			<form onSubmit={handleSubmit(onSubmit)} className="space-y-6 text-white">
				<div className="grid grid-cols-1 gap-5">
					{companyFields.map(({ name, label, placeholder, type, rules }) => (
						<AuthField key={name} label={label} error={errors[name]?.message as string | undefined}>
							<input
								{...register(name, rules)}
								type={type}
								placeholder={placeholder}
								className={authInputClassName}
							/>
						</AuthField>
					))}
					<div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
						<AuthField label={phoneField.label}>
							<input
								{...register(phoneField.name)}
								placeholder={phoneField.placeholder}
								className={authInputClassName}
							/>
						</AuthField>
						<AuthField label={registrationField.label}>
							<input
								{...register(registrationField.name)}
								placeholder={registrationField.placeholder}
								className={authInputClassName}
							/>
						</AuthField>
					</div>
					<AuthField label={addressField.label}>
						<textarea
							{...register(addressField.name)}
							placeholder={addressField.placeholder}
							rows={2}
							className={`${authInputClassName} resize-none placeholder:text-white/40`}
						/>
					</AuthField>
					<AuthField label={taxField.label}>
						<input
							{...register(taxField.name)}
							placeholder={taxField.placeholder}
							className={authInputClassName}
						/>
					</AuthField>
					<div className="border-t border-white/10 pt-5">
						<h2 className="text-lg font-semibold text-white">Admin Details</h2>
					</div>
					<div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
						<AuthField
							label={adminFirstNameField.label}
							error={errors[adminFirstNameField.name]?.message as string | undefined}
						>
							<input
								{...register(adminFirstNameField.name, adminFirstNameField.rules)}
								placeholder={adminFirstNameField.placeholder}
								className={authInputClassName}
							/>
						</AuthField>
						<AuthField
							label={adminLastNameField.label}
							error={errors[adminLastNameField.name]?.message as string | undefined}
						>
							<input
								{...register(adminLastNameField.name, adminLastNameField.rules)}
								placeholder={adminLastNameField.placeholder}
								className={authInputClassName}
							/>
						</AuthField>
					</div>
					<AuthField
						label={adminEmailField.label}
						error={errors[adminEmailField.name]?.message as string | undefined}
					>
						<input
							{...register(adminEmailField.name, adminEmailField.rules)}
							type="email"
							placeholder={adminEmailField.placeholder}
							className={authInputClassName}
						/>
					</AuthField>
					<div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
						<AuthField
							label={adminPasswordField.label}
							error={errors[adminPasswordField.name]?.message as string | undefined}
						>
							<input
								{...register(adminPasswordField.name, adminPasswordField.rules)}
								type="password"
								placeholder={adminPasswordField.placeholder}
								className={authInputClassName}
							/>
						</AuthField>
						<AuthField
							label={confirmPasswordField.label}
							error={errors[confirmPasswordField.name]?.message as string | undefined}
						>
							<input
								{...register(confirmPasswordField.name, confirmPasswordField.rules)}
								type="password"
								placeholder={confirmPasswordField.placeholder}
								className={authInputClassName}
							/>
						</AuthField>
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
		</AuthLayout>
	)
}

