"use client"

interface PipelineControlButtonProps {
	onClick: () => void
	disabled?: boolean
	label: string
}

export function PipelineControlButton({ onClick, disabled = false, label }: PipelineControlButtonProps) {
	return (
		<button
			className="px-8 py-4 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
			onClick={onClick}
			disabled={disabled}
		>
			{label}
		</button>
	)
}
