type AuthNoticeProps = {
	variant: "error" | "success"
	message: string
}

const styles = {
	error: "border-red-500/40 bg-red-500/10 text-red-200",
	success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
}

export function AuthNotice({ variant, message }: AuthNoticeProps) {
	return <div className={`mb-4 rounded-xl border px-4 py-3 text-sm ${styles[variant]}`}>{message}</div>
}
