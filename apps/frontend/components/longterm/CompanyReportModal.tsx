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
import { generateCompanyReportPdf } from "@/components/utils/generateCompanyReportPdf"

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
		if (key === "_id" || key === "id" || key === "ticker") return false
		if (!value || value === "") return false
		return true
	}

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto bg-white border-gray-200 p-0 [&>button]:text-gray-600 [&>button]:hover:text-gray-900 [&>button]:hover:bg-gray-100 [&>button]:rounded-md [&>button]:p-1 [&>button]:transition-colors">
				<div id="company-report-pdf" className="p-8">
					<DialogHeader className="px-0 pt-0 pb-6 border-b border-gray-200">
						<DialogTitle className="text-2xl font-bold text-gray-900">
							{report?.company_name || `Company Report: ${ticker}`}
						</DialogTitle>
						{report?.ticker && (
							<p className="text-sm text-gray-500 mt-1">Ticker: {report.ticker}</p>
						)}
					</DialogHeader>

					{!loading && !error && report && (
						<div className="pt-4">
							<button
								onClick={() => generateCompanyReportPdf(report)}
								className="px-4 py-2 bg-black text-white rounded hover:bg-gray-800"
							>
								Download PDF
							</button>
						</div>
					)}

					{loading && (
						<div className="flex items-center justify-center py-12">
							<Loader2 className="w-6 h-6 animate-spin text-gray-600" />
							<span className="ml-3 text-gray-700">Loading report...</span>
						</div>
					)}

					{error && (
						<div className="mt-6 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-700">
							{error}
						</div>
					)}

					{!loading && !error && report && (
						<div className="py-6 space-y-8 text-gray-900">
							{report.company_description && (
								<section>
									<h2 className="text-xl font-semibold mb-3 text-gray-900">Company Description</h2>
									<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
										{report.company_description}
									</p>
								</section>
							)}

							{report.business_model && (
								<section>
									<h2 className="text-xl font-semibold mb-3 text-gray-900">Business Model</h2>
									<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
										{report.business_model}
									</p>
								</section>
							)}

							{(report.segment_exposure || report.geographic_exposure || report.market_cap) && (
								<section>
									<h2 className="text-xl font-semibold mb-3 text-gray-900">Business Overview</h2>
									<div className="space-y-3">
										{report.market_cap && (
											<div>
												<h3 className="text-base font-medium mb-1 text-gray-800">Market Capitalization</h3>
												<p className="text-base leading-relaxed text-gray-700">{report.market_cap}</p>
											</div>
										)}
										{report.segment_exposure && (
											<div>
												<h3 className="text-base font-medium mb-1 text-gray-800">Segment Exposure</h3>
												<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
													{report.segment_exposure}
												</p>
											</div>
										)}
										{report.geographic_exposure && (
											<div>
												<h3 className="text-base font-medium mb-1 text-gray-800">Geographic Exposure</h3>
												<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
													{report.geographic_exposure}
												</p>
											</div>
										)}
									</div>
								</section>
							)}

							{report.leadership_governance && (
								<section>
									<h2 className="text-xl font-semibold mb-3 text-gray-900">Leadership & Governance</h2>
									<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
										{report.leadership_governance}
									</p>
								</section>
							)}

							{(report.major_clients || report.major_partnerships) && (
								<section>
									<h2 className="text-xl font-semibold mb-3 text-gray-900">Clients & Partnerships</h2>
									<div className="space-y-3">
										{report.major_clients && (
											<div>
												<h3 className="text-base font-medium mb-1 text-gray-800">Major Clients</h3>
												<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
													{report.major_clients}
												</p>
											</div>
										)}
										{report.major_partnerships && (
											<div>
												<h3 className="text-base font-medium mb-1 text-gray-800">Major Partnerships</h3>
												<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
													{report.major_partnerships}
												</p>
											</div>
										)}
									</div>
								</section>
							)}

							{(report.recent_strategic_actions || report.rnd_intensity || report.brand_value_drivers) && (
								<section>
									<h2 className="text-xl font-semibold mb-3 text-gray-900">Strategic Information</h2>
									<div className="space-y-3">
										{report.recent_strategic_actions && (
											<div>
												<h3 className="text-base font-medium mb-1 text-gray-800">Recent Strategic Actions</h3>
												<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
													{report.recent_strategic_actions}
												</p>
											</div>
										)}
										{report.brand_value_drivers && (
											<div>
												<h3 className="text-base font-medium mb-1 text-gray-800">Brand Value Drivers</h3>
												<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
													{report.brand_value_drivers}
												</p>
											</div>
										)}
										{report.rnd_intensity && (
											<div>
												<h3 className="text-base font-medium mb-1 text-gray-800">R&D Intensity</h3>
												<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
													{report.rnd_intensity}
												</p>
											</div>
										)}
									</div>
								</section>
							)}

							{report.negatives_risks && (
								<section>
									<h2 className="text-xl font-semibold mb-3 text-gray-900">Risks & Challenges</h2>
									<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
										{report.negatives_risks}
									</p>
								</section>
							)}

							{Object.entries(report).map(([key, value]) => {
								if (!shouldDisplayField(key, value)) return null
								if ([
									"company_name", "company_description", "business_model",
									"market_cap", "segment_exposure", "geographic_exposure",
									"leadership_governance", "major_clients", "major_partnerships",
									"recent_strategic_actions", "rnd_intensity", "brand_value_drivers",
									"negatives_risks", "created_at", "updated_at"
								].includes(key)) return null

								return (
									<section key={key}>
										<h2 className="text-xl font-semibold mb-3 text-gray-900">{formatFieldName(key)}</h2>
										<p className="text-base leading-relaxed text-gray-700 whitespace-pre-wrap">
											{typeof value === "string" ? value : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value)}
										</p>
									</section>
								)
							})}

							{(report.created_at || report.updated_at) && (
								<section className="pt-4 border-t border-gray-200">
									<div className="text-sm text-gray-500 space-y-1">
										{report.created_at && (
											<p>Created: {new Date(report.created_at).toLocaleString()}</p>
										)}
										{report.updated_at && (
											<p>Last Updated: {new Date(report.updated_at).toLocaleString()}</p>
										)}
									</div>
								</section>
							)}
						</div>
					)}
				</div>
			</DialogContent>
		</Dialog>
	)
}

