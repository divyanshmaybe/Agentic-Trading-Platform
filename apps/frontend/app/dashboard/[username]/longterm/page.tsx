"use client"

import { useState, useMemo, useEffect } from "react"
import { useParams } from "next/navigation"
import { Loader2, Play } from "lucide-react"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/useAuth"
import { AgentOverview, AgentTradesTable } from "@/components/agent"
import { PortfolioSnapshots } from "@/components/portfolio/PortfolioSnapshots"
import { useAgentDashboard } from "@/hooks/useAgentDashboard"
import { useLowRiskEvents } from "@/components/hooks/useLowRiskEvents"
import { createDynamicPieChartData } from "@/components/dashboard/chartConfig"
import {
	PipelineEventsCard,
	IndustryDistributionChart,
	PortfolioAllocationChart,
	EmptyStateMessage,
	StreamingEventsView,
	BuyTradeModal,
	CooldownModal
} from "@/components/longterm"
import "@/lib/chart"

export default function LongTermPage() {
	const params = useParams()
	const username = params.username as string

	// SECURE: Get user data from server-validated token, NOT localStorage
	const { user: authUser, loading: authLoading } = useAuth()

	const { data: agentData, loading: agentLoading, isAllocating } = useAgentDashboard("low_risk")
	const { events, loading: eventsLoading, startStreaming, stopStreaming, streaming, hasSummary, clearEvents } = useLowRiskEvents()
	const [showAllEvents, setShowAllEvents] = useState(false)
	const [triggeringPipeline, setTriggeringPipeline] = useState(false)
	const [pipelineError, setPipelineError] = useState<string | null>(null)
	const [buyModalOpen, setBuyModalOpen] = useState(false)
	const [rebalancing, setRebalancing] = useState(false)
	const [rebalanceError, setRebalanceError] = useState<string | null>(null)
	const [triggeringAgent, setTriggeringAgent] = useState(false)
	const [cooldownModalOpen, setCooldownModalOpen] = useState(false)
	const [cooldownData, setCooldownData] = useState<{
		daysElapsed: number
		daysRemaining: number
		message: string
	} | null>(null)

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

	const tradeList = useMemo(() => {
		return summaryEvent?.content?.trade_list || []
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

	const handleRebalance = async () => {
		setRebalancing(true)
		setRebalanceError(null)

		try {
			// Stop streaming first
			stopStreaming()

			// Call rebalance API
			const response = await fetch("/api/notifications/lowrisk/rebalance", {
				method: "POST",
				credentials: "include",
			})

			if (!response.ok) {
				const data = await response.json().catch(() => ({ error: "Failed to rebalance" }))
				throw new Error(data.error || data.message || "Failed to rebalance")
			}

			const data = await response.json()

			if (!data.success) {
				throw new Error(data.message || "Failed to rebalance")
			}

			// Clear events from state
			clearEvents()

			// Start streaming again to receive new events
			startStreaming()
		} catch (error) {
			console.error("[LongTerm Page] Failed to rebalance:", error)
			const errorMessage = error instanceof Error ? error.message : "Failed to rebalance. Please try again."
			
			// Check if this is a 6-month cooldown error
			if (errorMessage.includes("6 months") || errorMessage.includes("cooldown")) {
				// Parse the error message to extract days elapsed and days remaining
				// Expected format: "Last run was X days ago. Please wait Y more days."
				const daysElapsedMatch = errorMessage.match(/(\d+)\s+days ago/)
				const daysRemainingMatch = errorMessage.match(/wait\s+(\d+)\s+more days/)
				
				const daysElapsed = daysElapsedMatch ? parseInt(daysElapsedMatch[1], 10) : 0
				const daysRemaining = daysRemainingMatch ? parseInt(daysRemainingMatch[1], 10) : 0
				
				setCooldownData({
					daysElapsed,
					daysRemaining,
					message: errorMessage,
				})
				setCooldownModalOpen(true)
			} else {
				// For non-cooldown errors, show the regular error message
				setRebalanceError(errorMessage)
			}
		} finally {
			setRebalancing(false)
		}
	}

	// Handle triggering low_risk agent
	const handleTriggerAgent = async () => {
		setTriggeringAgent(true)
		try {
			const authServerUrl = process.env.NEXT_PUBLIC_AUTH_BASE_URL 
				? process.env.NEXT_PUBLIC_AUTH_BASE_URL.replace("/api/auth", "")
				: "http://localhost:4000"
			
			// Get auth token
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

			const response = await fetch(`${authServerUrl}/api/user/subscriptions`, {
				method: "POST",
				headers,
				credentials: "include",
				body: JSON.stringify({
					action: "subscribe",
					agent: "low_risk",
				}),
			})

			const data = await response.json()

			if (!response.ok) {
				throw new Error(data.message || data.error || "Failed to trigger low_risk agent")
			}

			// Show success message or handle as needed
			alert("Low-risk agent triggered successfully!")
		} catch (error) {
			console.error("Failed to trigger low_risk agent:", error)
			alert(error instanceof Error ? error.message : "Failed to trigger low_risk agent")
		} finally {
			setTriggeringAgent(false)
		}
	}

	const hasEvents = events.length > 0

	// Ensure all events are available (including summary)
	const allEvents = useMemo(() => {
		return events // All events including summary
	}, [events])

	// Check pipeline status on mount and auto-start streaming if running
	useEffect(() => {
		const checkPipelineStatus = async () => {
			try {
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

				const response = await fetch(`${portfolioServerUrl}/api/low-risk/status`, {
					method: "GET",
					headers,
					credentials: "include",
				})

				if (!response.ok) {
					console.warn('[LongTerm Page] Failed to check pipeline status:', response.statusText)
					return
				}

				const data = await response.json()
				
				// If pipeline is running, auto-start the SSE stream
				if (data.running && data.status === "running") {
					console.log('[LongTerm Page] Pipeline already running, auto-starting stream...', {
						elapsed_minutes: data.elapsed_minutes
					})
					startStreaming()
				}
			} catch (error) {
				console.warn('[LongTerm Page] Failed to check pipeline status:', error)
			}
		}

		// Only check on mount if not already streaming
		if (!streaming && authUser) {
			checkPipelineStatus()
		}
	}, [authUser]) // Only run on mount when authUser is available

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
					action={
						<Button
							onClick={handleTriggerAgent}
							disabled={triggeringAgent}
							className="border border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
						>
							{triggeringAgent ? (
								<>
									<Loader2 className="mr-2 size-4 animate-spin" />
									Triggering...
								</>
							) : (
								<>
									<Play className="mr-2 size-4" />
									Trigger Low-Risk Agent
								</>
							)}
						</Button>
					}
				/>

				<section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
					<AgentOverview data={agentData} loading={agentLoading} isAllocating={isAllocating} />
					<AgentTradesTable trades={agentData?.recent_trades ?? []} loading={agentLoading} agentId={agentData?.agent_id} />
				</section>

				<section>
					<PortfolioSnapshots agentType="low_risk" title="Long-Term Strategy Snapshot History" />
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
										{/* Show error messages */}
										{(pipelineError || rebalanceError) && (
											<div className="rounded-lg border border-white/10 bg-white/8 p-4 text-white/70">
												{pipelineError && <p className="text-sm">{pipelineError}</p>}
												{rebalanceError && <p className="text-sm">{rebalanceError}</p>}
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

											{/* Buy Stocks and Rebalance Buttons */}
											{hasSummary && finalPortfolio.length > 0 && agentData?.portfolio_id && (
												<div className="flex justify-center gap-4">
													<button
														onClick={() => setBuyModalOpen(true)}
														className="rounded-lg bg-emerald-500 hover:bg-emerald-600 px-6 py-3 text-white font-semibold transition-colors shadow-lg hover:shadow-xl disabled:opacity-50 disabled:cursor-not-allowed"
														disabled={rebalancing || streaming}
													>
														Buy Stocks
													</button>
													<button
														onClick={handleRebalance}
														disabled={rebalancing || streaming}
														className="rounded-lg bg-blue-500 hover:bg-blue-600 px-6 py-3 text-white font-semibold transition-colors shadow-lg hover:shadow-xl disabled:opacity-50 disabled:cursor-not-allowed"
													>
														{rebalancing ? "Rebalancing..." : "Rebalance"}
													</button>
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

			{/* Buy Trade Modal */}
			{agentData?.portfolio_id && (
				<BuyTradeModal
					open={buyModalOpen}
					onOpenChange={setBuyModalOpen}
					finalPortfolio={finalPortfolio}
					tradeList={tradeList}
					portfolioId={agentData.portfolio_id}
					allocationId={agentData.allocation?.id}
				/>
			)}

			{/* Cooldown Modal */}
			{cooldownData && (
				<CooldownModal
					open={cooldownModalOpen}
					onOpenChange={setCooldownModalOpen}
					daysElapsed={cooldownData.daysElapsed}
					daysRemaining={cooldownData.daysRemaining}
					message={cooldownData.message}
				/>
			)}
		</div>
	)
}
