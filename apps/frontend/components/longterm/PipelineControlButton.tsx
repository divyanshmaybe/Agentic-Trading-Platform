"use client"

interface PipelineControlButtonProps {
	onClick: () => void
	disabled?: boolean
	label: string
}

export function PipelineControlButton({ onClick, disabled = false, label }: PipelineControlButtonProps) {
	return (
		<button
			className="px-8 py-4 rounded-xl border border-white/10 bg-white/8 text-[#fafafa] font-semibold hover:bg-white/10 hover:border-white/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed backdrop-blur-sm"
			onClick={onClick}
			disabled={disabled}
		>
			{label}
		</button>
	)
}
