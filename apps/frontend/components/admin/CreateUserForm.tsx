import type { ComponentPropsWithoutRef, FormEventHandler } from "react"
import type { FieldErrors, UseFormRegister } from "react-hook-form"

import { Button } from "@/components/ui/button"

import type { CreateUserFormValues } from "./types"

type CreateUserFormProps = {
  register: UseFormRegister<CreateUserFormValues>
  errors: FieldErrors<CreateUserFormValues>
  onSubmit: FormEventHandler<HTMLFormElement>
  isSubmitting: boolean
  errorMessage?: string | null
  successMessage?: string | null
  submitLabel?: string
  className?: string
} & ComponentPropsWithoutRef<"form">

export function CreateUserForm({
  register,
  errors,
  onSubmit,
  isSubmitting,
  errorMessage,
  successMessage,
  submitLabel = "Create user",
  className = "",
  ...formProps
}: CreateUserFormProps) {
  return (
    <form
      onSubmit={onSubmit}
      className={`flex h-full w-full flex-col gap-4 ${className}`}
      {...formProps}
    >
      {errorMessage && (
        <div
          className="rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
          role="alert"
        >
          {errorMessage}
        </div>
      )}
      {successMessage && (
        <div
          className="rounded-lg border border-emerald-400/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200"
          role="status"
        >
          {successMessage}
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="text-white/70">First Name</span>
          <input
            {...register("firstName", { required: "First name is required" })}
            type="text"
            placeholder="Jane"
            className="w-full rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-white placeholder:text-white/40 focus:outline-none"
          />
          {errors.firstName && (
            <span className="text-xs text-rose-300">{errors.firstName.message}</span>
          )}
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-white/70">Last Name</span>
          <input
            {...register("lastName", { required: "Last name is required" })}
            type="text"
            placeholder="Smith"
            className="w-full rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-white placeholder:text-white/40 focus:outline-none"
          />
          {errors.lastName && (
            <span className="text-xs text-rose-300">{errors.lastName.message}</span>
          )}
        </label>
      </div>
      <label className="space-y-1 text-sm">
        <span className="text-white/70">Email</span>
        <input
          {...register("email", {
            required: "Email is required",
            pattern: { value: /[^\s@]+@[^\s@]+\.[^\s@]+/, message: "Enter a valid email" },
          })}
          type="email"
          placeholder="staff@acme.com"
          className="w-full rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-white placeholder:text-white/40 focus:outline-none"
        />
        {errors.email && <span className="text-xs text-rose-300">{errors.email.message}</span>}
      </label>
      <label className="space-y-1 text-sm">
        <span className="text-white/70">Password</span>
        <input
          {...register("password", {
            required: "Password is required",
            minLength: { value: 8, message: "Use at least 8 characters" },
          })}
          type="password"
          placeholder="SecurePass123!"
          className="w-full rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-white placeholder:text-white/40 focus:outline-none"
        />
        {errors.password && (
          <span className="text-xs text-rose-300">{errors.password.message}</span>
        )}
      </label>
      <label className="space-y-1 text-sm">
        <span className="text-white/70">Role</span>
        <select
          {...register("role", { required: true })}
          className="w-full rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-white focus:outline-none"
        >
          <option value="staff">Staff</option>
          <option value="viewer">Customer (Viewer)</option>
        </select>
      </label>
      <Button
        type="submit"
        disabled={isSubmitting}
        className="mt-auto w-full border border-white/10 bg-white/10 text-white hover:bg-white/20"
      >
        {isSubmitting ? "Creating..." : submitLabel}
      </Button>
    </form>
  )
}

