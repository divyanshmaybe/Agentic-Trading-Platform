"use client"

import { PipelineControlButton } from "./PipelineControlButton"

interface EmptyStateMessageProps {
	message: string
	showButton?: boolean
	onButtonClick?: () => void
	buttonLabel?: string
	buttonDisabled?: boolean
}

export function EmptyStateMessage({
	message,
	showButton = false,
	onButtonClick,
	buttonLabel = "Run Pipeline",
	buttonDisabled = false
}: EmptyStateMessageProps) {
	return (
		<div className="flex flex-1 flex-col items-center justify-center gap-6">
			<p className="text-center text-white/70 text-lg max-w-2xl">{message}</p>
			{showButton && onButtonClick && (
				<div className="flex items-center justify-center gap-4">
					<PipelineControlButton
						onClick={onButtonClick}
						disabled={buttonDisabled}
						label={buttonLabel}
					/>
				</div>
			)}
		</div>
	)
}
