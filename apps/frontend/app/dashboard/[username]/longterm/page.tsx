"use client"

import { useState, useMemo, useEffect } from "react"
import { useParams } from "next/navigation"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { useAuth } from "@/hooks/useAuth"
import { AgentOverview, AgentTradesTable } from "@/components/agent"
import { useAgentDashboard } from "@/hooks/useAgentDashboard"
import { useLowRiskEvents } from "@/components/hooks/useLowRiskEvents"
import { createDynamicPieChartData } from "@/components/dashboard/chartConfig"
import {
	PipelineEventsCard,
	IndustryDistributionChart,
	PortfolioAllocationChart,
	EmptyStateMessage,
	StreamingEventsView
} from "@/components/longterm"
import "@/lib/chart"

export default function LongTermPage() {
	const params = useParams()
	const username = params.username as string

	// SECURE: Get user data from server-validated token, NOT localStorage
	const { user: authUser, loading: authLoading } = useAuth()

	const { data: agentData, loading: agentLoading, isAllocating } = useAgentDashboard("low_risk")
	const { events, loading: eventsLoading, startStreaming, stopStreaming, streaming, hasSummary } = useLowRiskEvents()
	const [showAllEvents, setShowAllEvents] = useState(false)
	const [triggeringPipeline, setTriggeringPipeline] = useState(false)
	const [pipelineError, setPipelineError] = useState<string | null>(null)

	// Extract summary event data
	const summaryEvent = useMemo(() => {
		return events.find((event) => event.kind === "summary") || null
	}, [events])

	// Extract industry done event
	const industryDoneEvent = useMemo(() => {
		return events.find((event) => event.kind === "industry" && event.status === "done") || null
	}, [events])

	const industryList = useMemo(() => {
		// Prioritize industry done event's industries, fallback to summary event's industries
		if (industryDoneEvent?.content?.industries) {
			return industryDoneEvent.content.industries
		}
		return summaryEvent?.content?.industry_list || []
	}, [industryDoneEvent, summaryEvent])

	const finalPortfolio = useMemo(() => {
		return summaryEvent?.content?.final_portfolio || []
	}, [summaryEvent])

	const summary = useMemo(() => {
		return summaryEvent?.content?.summary || null
	}, [summaryEvent])

	// Create pie chart data
	const industryChartData = useMemo(() => createDynamicPieChartData(industryList), [industryList])
	const portfolioChartData = useMemo(() => createDynamicPieChartData(finalPortfolio), [finalPortfolio])

	const handleRunPipeline = async () => {
		setTriggeringPipeline(true)
		setPipelineError(null)
		setShowAllEvents(false) // Close events view when starting new stream

		try {
			// Default fund allocation: ₹100,000
			const fundAllocated = 100000.0

			// Get portfolio server URL from environment
			const portfolioServerUrl = process.env.NEXT_PUBLIC_PORTFOLIO_API_URL || process.env.NEXT_PUBLIC_PORTFOLIO_SERVER_URL || "http://localhost:8000"
			
			// Get auth token from cookie or localStorage
			let token: string | null = null
			if (typeof window !== "undefined") {
				const match = document.cookie.match(/(^| )access_token=([^;]+)/)
				token = match ? match[2] : localStorage.getItem("access_token")
			}

			const headers: HeadersInit = {
				"Content-Type": "application/json",
			}
			if (token) {
				headers["Authorization"] = `Bearer ${token}`
			}

			const response = await fetch(`${portfolioServerUrl}/api/low-risk/trigger`, {
				method: "POST",
				headers,
				credentials: "include",
				body: JSON.stringify({
					fund_allocated: fundAllocated,
				}),
			})

			// Check if response is JSON before parsing
			const contentType = response.headers.get("content-type")
			if (!contentType || !contentType.includes("application/json")) {
				const text = await response.text()
				throw new Error(`Invalid response format: ${text.substring(0, 100)}`)
			}

			const data = await response.json()

			if (!response.ok) {
				throw new Error(data.message || data.detail || "Failed to trigger pipeline")
			}

			// Check if pipeline was successfully triggered or already running
			if (data.success) {
				// Pipeline started successfully, start streaming to receive events
				startStreaming()
			} else {
				// Pipeline already running - show message but still start streaming to see updates
				setPipelineError(data.message || "Pipeline is already running")
				startStreaming()
			}
		} catch (error) {
			console.error("[LongTerm Page] Failed to trigger pipeline:", error)
			setPipelineError(
				error instanceof Error ? error.message : "Failed to trigger pipeline. Please try again."
			)
		} finally {
			setTriggeringPipeline(false)
		}
	}

	const handleStopPipeline = () => {
		stopStreaming()
	}

	const hasEvents = events.length > 0

	// Ensure all events are available (including summary)
	const allEvents = useMemo(() => {
		return events // All events including summary
	}, [events])

	// Console log events on page reload and when events change
	useEffect(() => {
		console.log('[LongTerm Page] Events fetched/updated:', {
			totalEvents: events.length,
			events: events,
			hasSummary: hasSummary,
			eventKinds: events.map(e => e.kind),
			eventIds: events.map(e => e.id)
		})
	}, [events, hasSummary])

	// Show loading state while auth is being verified
	if (authLoading || !authUser) {
		return (
			<div className="flex min-h-screen items-center justify-center bg-[#0c0c0c] text-[#fafafa]">
				<div className="text-white/60">Loading...</div>
			</div>
		)
	}

	return (
		<div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
			<DashboardHeader userName={authUser.firstName} username={username} userRole={authUser.role} />

			<Container className="max-w-10xl space-y-8 px-4 py-10 sm:px-6 lg:px-12 xl:px-16">
				<PageHeading
					title="Long-Term Strategy Center"
					tagline="Monitor your low-risk positions and conservative strategies."
				/>

				<section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
					<AgentOverview data={agentData} loading={agentLoading} isAllocating={isAllocating} />
					<AgentTradesTable trades={agentData?.recent_trades ?? []} loading={agentLoading} />
				</section>

				{!agentLoading && !isAllocating && agentData !== null && (
					<div className="w-full">
						{/* Large centered message box with text and button inside */}
						<div className={`card-glass w-full min-h-screen rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur p-10 ${industryDoneEvent && industryList.length > 0 && !hasSummary ? 'flex flex-row gap-6' : 'flex flex-col gap-6'}`}>
							{!streaming ? (
								/* Content when not streaming */
								eventsLoading ? (
									/* Loading state */
									<div className="flex flex-1 flex-col items-center justify-center gap-6">
										<div className="text-white/60 text-sm">Loading events...</div>
									</div>
								) : hasEvents ? (
									/* Show toggleable events when events exist */
									<div className={`flex flex-col gap-6 ${industryDoneEvent && industryList.length > 0 && !hasSummary ? 'flex-1' : 'flex-1'}`}>
										{/* Show error message if pipeline trigger failed */}
										{pipelineError && (
											<div className="rounded-lg border border-white/10 bg-white/8 p-4 text-white/70">
												<p className="text-sm">{pipelineError}</p>
											</div>
										)}

										{!hasSummary && (
											<EmptyStateMessage
												message="Start your long-term investment journey with our automated low-risk pipeline. Build wealth steadily through carefully selected positions."
												showButton={true}
												onButtonClick={handleRunPipeline}
												buttonLabel={triggeringPipeline ? "Starting..." : "Run Pipeline"}
												buttonDisabled={triggeringPipeline || streaming}
											/>
										)}

										{/* Toggleable events section */}
										<div className="flex-1 w-full space-y-8">
											<PipelineEventsCard
												events={allEvents}
												isExpanded={showAllEvents}
												onToggle={() => setShowAllEvents(!showAllEvents)}
											/>

											{/* Summary metric cards */}
											{hasSummary && summary && (
												<div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4 animate-[fadeIn_0.4s_ease-out]">
													<div
														className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm flex flex-col gap-1"
														style={{ animationDelay: "40ms" }}
													>
														<div className="text-xs uppercase tracking-wide text-white/45">
															Total Stocks
														</div>
														<div className="mt-2 text-2xl font-semibold text-[#fafafa]">
															{summary.total_stocks}
														</div>
													</div>
													<div
														className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm flex flex-col gap-1"
														style={{ animationDelay: "80ms" }}
													>
														<div className="text-xs uppercase tracking-wide text-white/45">
															Total Trades
														</div>
														<div className="mt-2 text-2xl font-semibold text-[#fafafa]">
															{summary.total_trades}
														</div>
													</div>
													<div
														className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm flex flex-col gap-1"
														style={{ animationDelay: "120ms" }}
													>
														<div className="text-xs uppercase tracking-wide text-white/45">
															Total Invested
														</div>
														<div className="mt-2 text-2xl font-semibold text-[#fafafa]">
															₹{summary.total_invested?.toLocaleString()}
														</div>
													</div>
													<div
														className="rounded-xl border border-white/10 bg-white/8 p-4 text-white/70 backdrop-blur-sm flex flex-col gap-1"
														style={{ animationDelay: "160ms" }}
													>
														<div className="text-xs uppercase tracking-wide text-white/45">
															Utilization Rate
														</div>
														<div className="mt-2 text-2xl font-semibold text-[#fafafa]">
															{summary.utilization_rate?.toFixed(1)}%
														</div>
													</div>
												</div>
											)}

											{/* Both charts inside card when summary event exists */}
											{hasSummary && (industryList.length > 0 || finalPortfolio.length > 0) && (
												<div className="grid grid-cols-1 gap-6 md:grid-cols-2">
													{industryList.length > 0 && (
														<IndustryDistributionChart
															industryList={industryList}
															chartData={industryChartData}
														/>
													)}
													{finalPortfolio.length > 0 && (
														<PortfolioAllocationChart
															finalPortfolio={finalPortfolio}
															chartData={portfolioChartData}
														/>
													)}
												</div>
											)}

										</div>
									</div>
									) : (
									/* Show run pipeline button when no events */
									!hasSummary && (
										<>
											{/* Show error message if pipeline trigger failed */}
											{pipelineError && (
												<div className="rounded-lg border border-white/10 bg-white/8 p-4 text-white/70 mb-4">
													<p className="text-sm">{pipelineError}</p>
												</div>
											)}
											<EmptyStateMessage
												message="Start your long-term investment journey with our automated low-risk pipeline. Build wealth steadily through carefully selected positions."
												showButton={true}
												onButtonClick={handleRunPipeline}
												buttonLabel={triggeringPipeline ? "Starting..." : "Run Pipeline"}
												buttonDisabled={triggeringPipeline || streaming}
											/>
										</>
									)
								)
							) : (
								/* Streaming layout with events */
								<div className={`flex flex-col gap-6 ${industryDoneEvent && industryList.length > 0 && !hasSummary ? 'flex-1' : 'flex-1'}`}>
									{/* Top section with AI thinking indicator */}
									{!hasSummary && (
										<div className="flex flex-col items-center justify-center gap-6 py-4">
											<div className="flex items-center gap-3">
												{/* Pulsing dot */}
												<div className="w-3 h-3 rounded-full bg-cyan-400 animate-pulse-dot"></div>
												{/* Blinking text */}
												<span className="text-white/70 text-lg font-medium animate-blink-text">
													Thinking…
												</span>
											</div>
										</div>
									)}

									{/* Streaming events section inside the card */}
									<StreamingEventsView events={events} />

									{/* Both charts inside card when summary event exists (streaming) */}
									{hasSummary && (industryList.length > 0 || finalPortfolio.length > 0) && (
										<div className="grid grid-cols-1 gap-6 md:grid-cols-2">
											{industryList.length > 0 && (
												<IndustryDistributionChart
													industryList={industryList}
													chartData={industryChartData}
												/>
											)}
											{finalPortfolio.length > 0 && (
												<PortfolioAllocationChart
													finalPortfolio={finalPortfolio}
													chartData={portfolioChartData}
												/>
											)}
										</div>
									)}
								</div>
							)}

							{/* Industry chart on the right when industry done event exists (only if no summary) */}
							{industryDoneEvent && industryList.length > 0 && !hasSummary && (
								<div className="flex-1">
									<IndustryDistributionChart
										industryList={industryList}
										chartData={industryChartData}
									/>
								</div>
							)}
						</div>
					</div>
				)}
			</Container>
		</div>
	)
}
