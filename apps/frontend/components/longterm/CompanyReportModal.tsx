"use client"

import { useState, useEffect } from "react"
import { Loader2 } from "lucide-react"
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog"
import { apiClient } from "@/lib/api"

interface CompanyReport {
	ticker: string
	company_name?: string
	company_description?: string
	business_model?: string
	market_cap?: string
	geographic_exposure?: string
	segment_exposure?: string
	brand_value_drivers?: string
	leadership_governance?: string
	major_clients?: string
	major_partnerships?: string
	recent_strategic_actions?: string
	rnd_intensity?: string
	negatives_risks?: string
	created_at?: string
	updated_at?: string
	[key: string]: any
}

interface CompanyReportModalProps {
	open: boolean
	onOpenChange: (open: boolean) => void
	ticker: string
}

export function CompanyReportModal({ open, onOpenChange, ticker }: CompanyReportModalProps) {
	const [report, setReport] = useState<CompanyReport | null>(null)
	const [loading, setLoading] = useState(false)
	const [error, setError] = useState<string | null>(null)

	useEffect(() => {
		if (open && ticker) {
			setLoading(true)
			setError(null)
			setReport(null)

			apiClient
				.get<{ success: boolean; count: number; reports: CompanyReport[] }>(
					`/api/company/reports?ticker=${encodeURIComponent(ticker)}`
				)
				.then((response) => {
					if (response.success && response.reports && response.reports.length > 0) {
						setReport(response.reports[0])
					} else {
						setError("No report found for this ticker")
					}
				})
				.catch((err) => {
					console.error("[CompanyReportModal] Failed to fetch report:", err)
					setError(
						err instanceof Error
							? err.message
							: "Failed to load company report. Please try again."
					)
				})
				.finally(() => {
					setLoading(false)
				})
		}
	}, [open, ticker])

	const formatFieldName = (key: string): string => {
		return key
			.split("_")
			.map((word) => word.charAt(0).toUpperCase() + word.slice(1))
			.join(" ")
	}

	const shouldDisplayField = (key: string, value: any): boolean => {
		if (key === "_id" || key === "id") return false
		if (!value || value === "") return false
		return true
	}

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto bg-[#0c0c0c] border-white/10 text-white/90">
				<DialogHeader>
					<DialogTitle className="text-xl font-semibold text-white">
						Company Report: {ticker}
					</DialogTitle>
				</DialogHeader>

				{loading && (
					<div className="flex items-center justify-center py-12">
						<Loader2 className="w-6 h-6 animate-spin text-cyan-400" />
						<span className="ml-3 text-white/70">Loading report...</span>
					</div>
				)}

				{error && (
					<div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-red-300">
						{error}
					</div>
				)}

				{!loading && !error && report && (
					<div className="space-y-4">
						{Object.entries(report).map(([key, value]) => {
							if (!shouldDisplayField(key, value)) return null

							return (
								<div
									key={key}
									className="rounded-lg border border-white/10 bg-white/5 p-4"
								>
									<div className="mb-1 text-xs font-medium uppercase tracking-wide text-white/50">
										{formatFieldName(key)}
									</div>
									<div className="text-sm text-white/90 leading-relaxed">
										{typeof value === "string" ? (
											value
										) : typeof value === "object" ? (
											<pre className="whitespace-pre-wrap text-xs">
												{JSON.stringify(value, null, 2)}
											</pre>
										) : (
											String(value)
										)}
									</div>
								</div>
							)
						})}
					</div>
				)}
			</DialogContent>
		</Dialog>
	)
}

