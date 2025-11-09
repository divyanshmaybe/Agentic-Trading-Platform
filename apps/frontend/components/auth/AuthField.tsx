import { ReactNode } from "react"

type AuthFieldProps = {
	label: string
	error?: string
	children: ReactNode
}

export const authInputClassName =
	"w-full rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-white placeholder:text-white/50 outline-none ring-0 focus:border-white/25"

export function AuthField({ label, error, children }: AuthFieldProps) {
	return (
		<div className="space-y-2">
			<label className="block text-sm font-medium text-zinc-200">{label}</label>
			{children}
			{error ? <p className="text-sm text-rose-300">{error}</p> : null}
		</div>
	)
}


