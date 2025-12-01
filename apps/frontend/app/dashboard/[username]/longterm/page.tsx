"use client"

import { useState, useMemo, useEffect } from "react"
import { useParams } from "next/navigation"
import { ChevronDown, ChevronUp } from "lucide-react"
import { Pie } from "react-chartjs-2"
import { motion, AnimatePresence } from "framer-motion"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { useAuth } from "@/hooks/useAuth"
import { AgentOverview, AgentTradesTable } from "@/components/agent"
import { useAgentDashboard } from "@/hooks/useAgentDashboard"
import { useLowRiskEvents } from "@/components/hooks/useLowRiskEvents"
import { createDynamicPieChartData, summaryPieChartOptions, pieDepthPlugin } from "@/components/dashboard/chartConfig"
import "@/lib/chart"

// Reasoning Card Component with animated reasoning on hover
function ReasoningCard({ label, percentage, reasoning }: { label: string; percentage: number; reasoning?: string }) {
	const [isHovered, setIsHovered] = useState(false)

	return (
		<div
			className="relative rounded-lg border border-white/10 bg-black/20 p-3 transition-all hover:bg-black/30 hover:border-white/20"
			onMouseEnter={() => setIsHovered(true)}
			onMouseLeave={() => setIsHovered(false)}
		>
			<div className="flex items-center justify-between">
				<span className="font-medium text-[#fafafa]">{label}</span>
				<span className="text-sm text-white/70">{percentage.toFixed(2)}%</span>
			</div>
			<AnimatePresence>
				{isHovered && reasoning && (
					<motion.div
						initial={{ opacity: 0, height: 0, marginTop: 0 }}
						animate={{ opacity: 1, height: "auto", marginTop: 8 }}
						exit={{ opacity: 0, height: 0, marginTop: 0 }}
						transition={{ duration: 0.2, ease: "easeInOut" }}
						className="overflow-hidden"
					>
						<p className="text-sm text-white/60 leading-relaxed">{reasoning}</p>
					</motion.div>
				)}
			</AnimatePresence>
		</div>
	)
}

export default function LongTermPage() {
	const params = useParams()
	const username = params.username as string

	// SECURE: Get user data from server-validated token, NOT localStorage
	const { user: authUser, loading: authLoading } = useAuth()

	const { data: agentData, loading: agentLoading, isAllocating } = useAgentDashboard("low_risk")
	const { events, loading: eventsLoading, startStreaming, stopStreaming, streaming, hasSummary } = useLowRiskEvents()
	const [showAllEvents, setShowAllEvents] = useState(false)

	// Extract summary event data
	const summaryEvent = useMemo(() => {
		return events.find((event) => event.kind === "summary") || null
	}, [events])

	const industryList = useMemo(() => {
		return summaryEvent?.content?.industry_list || []
	}, [summaryEvent])

	const finalPortfolio = useMemo(() => {
		return summaryEvent?.content?.final_portfolio || []
	}, [summaryEvent])

	// Create pie chart data
	const industryChartData = useMemo(() => createDynamicPieChartData(industryList), [industryList])
	const portfolioChartData = useMemo(() => createDynamicPieChartData(finalPortfolio), [finalPortfolio])

	const handleRunPipeline = () => {
		startStreaming()
		setShowAllEvents(false) // Close events view when starting new stream
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
						<div className="card-glass w-full min-h-screen rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur p-10 flex flex-col gap-6">
							{!streaming ? (
								/* Content when not streaming */
								eventsLoading ? (
									/* Loading state */
									<div className="flex flex-1 flex-col items-center justify-center gap-6">
										<div className="text-white/60 text-sm">Loading events...</div>
									</div>
								) : hasEvents ? (
									/* Show toggleable events when events exist */
									<div className="flex flex-1 flex-col gap-6">
										<div className="flex flex-col items-center gap-6">
											{!hasSummary && (
												<p className="text-center text-white/70 text-lg max-w-2xl">
													Start your long-term investment journey with our automated low-risk pipeline.
													Build wealth steadily through carefully selected positions.
												</p>
											)}

											{!hasSummary && (
												<div className="flex items-center justify-center gap-4">
													<button
														className="px-8 py-4 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 transition-colors"
														onClick={handleRunPipeline}
													>
														Run Pipeline
													</button>
												</div>
											)}
										</div>

										{/* Toggleable events section */}
										<div className="flex-1 w-full">
											<button
												onClick={() => setShowAllEvents(!showAllEvents)}
												className="flex w-full items-center justify-between rounded-lg border border-white/10 bg-black/25 px-4 py-3 text-left transition hover:bg-black/35 backdrop-blur-sm mb-4"
											>
												<h3 className="text-lg font-semibold text-[#fafafa]">
													Pipeline Events ({events.length})
												</h3>
												{showAllEvents ? (
													<ChevronUp className="h-5 w-5 text-white/70" />
												) : (
													<ChevronDown className="h-5 w-5 text-white/70" />
												)}
											</button>

											{showAllEvents && (
												<div className="w-full mt-6">
													<div className="rounded-lg border border-white/10 bg-black/20 p-4">
														<div className="mb-3 text-sm text-white/60">
															Showing {allEvents.length} event{allEvents.length !== 1 ? 's' : ''} (including summary)
														</div>
														<div className="max-h-[600px] overflow-y-auto">
															<div className="space-y-4">
																{allEvents.length === 0 ? (
																	<div className="text-white/60 text-sm text-center py-4">No events to display</div>
																) : (
																	allEvents.map((event) => (
																		<div
																			key={event.id}
																			className="rounded-lg border border-white/10 bg-black/25 p-4 backdrop-blur-sm"
																		>
																			<div className="mb-2 text-xs font-semibold text-white/70 uppercase tracking-wide">
																				{event.kind || 'Unknown'} {event.kind === 'summary' && '✓'}
																			</div>
																			<pre className="text-xs text-white/90 whitespace-pre-wrap wrap-break-word font-mono">
																				{JSON.stringify(event, null, 2)}
																			</pre>
																		</div>
																	))
																)}
															</div>
														</div>
													</div>
												</div>
											)}

											{/* Pie Charts - shown when summary event exists */}
											{hasSummary && (industryList.length > 0 || finalPortfolio.length > 0) && (
												<div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-2 mt-6">
													{/* Industry Distribution Chart */}
													{industryList.length > 0 && (
														<div className="rounded-xl border border-white/10 bg-black/25 p-6 backdrop-blur-sm">
															<h4 className="mb-4 text-lg font-semibold text-[#fafafa]">Industry Distribution</h4>
															<div className="flex justify-center">
																<div className="w-full max-w-md">
																	<Pie
																		data={industryChartData}
																		options={summaryPieChartOptions}
																		plugins={[pieDepthPlugin]}
																	/>
																</div>
															</div>
															{/* Reasoning Cards */}
															<div className="mt-6 grid grid-cols-1 gap-3">
																{industryList.map((item: { name?: string; percentage: number; reasoning?: string }, index: number) => (
																	<ReasoningCard
																		key={index}
																		label={item.name || ""}
																		percentage={item.percentage}
																		reasoning={item.reasoning}
																	/>
																))}
															</div>
														</div>
													)}

													{/* Portfolio Allocation Chart */}
													{finalPortfolio.length > 0 && (
														<div className="rounded-xl border border-white/10 bg-black/25 p-6 backdrop-blur-sm">
															<h4 className="mb-4 text-lg font-semibold text-[#fafafa]">Portfolio Allocation</h4>
															<div className="flex justify-center">
																<div className="w-full max-w-md">
																	<Pie
																		data={portfolioChartData}
																		options={summaryPieChartOptions}
																		plugins={[pieDepthPlugin]}
																	/>
																</div>
															</div>
															{/* Reasoning Cards */}
															<div className="mt-6 grid grid-cols-1 gap-3">
																{finalPortfolio.map((item: { ticker?: string; percentage: number; reasoning?: string }, index: number) => (
																	<ReasoningCard
																		key={index}
																		label={item.ticker || ""}
																		percentage={item.percentage}
																		reasoning={item.reasoning}
																	/>
																))}
															</div>
														</div>
													)}
												</div>
											)}
										</div>
									</div>
								) : (
									/* Show run pipeline button when no events */
									<div className="flex flex-1 flex-col items-center justify-center gap-6">
										{!hasSummary && (
											<p className="text-center text-white/70 text-lg max-w-2xl">
												Start your long-term investment journey with our automated low-risk pipeline.
												Build wealth steadily through carefully selected positions.
											</p>
										)}

										{!hasSummary && (
											<div className="flex items-center justify-center gap-4">
												<button
													className="px-8 py-4 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
													onClick={handleRunPipeline}
													disabled={streaming}
												>
													Run Pipeline
												</button>
											</div>
										)}
									</div>
								)
							) : (
								/* Streaming layout with events */
								<div className="flex flex-1 flex-col gap-6">
									{/* Top section with message and buttons */}
									<div className="flex flex-col items-center gap-6">
										{!hasSummary && (
											<p className="text-center text-white/70 text-lg max-w-2xl">
												Start your long-term investment journey with our automated low-risk pipeline.
												Build wealth steadily through carefully selected positions.
											</p>
										)}

										{!hasSummary && (
											<div className="flex items-center justify-center gap-4">
												<button
													className="px-8 py-4 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
													onClick={handleRunPipeline}
													disabled={streaming}
												>
													Pipeline Running…
												</button>

												<button
													className="px-8 py-4 rounded-xl bg-red-600 text-white font-semibold hover:bg-red-700 transition-colors"
													onClick={handleStopPipeline}
												>
													Stop Pipeline
												</button>
											</div>
										)}
									</div>

									{/* Pie Charts - shown when summary event exists */}
									{hasSummary && (industryList.length > 0 || finalPortfolio.length > 0) && (
										<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
											{/* Industry Distribution Chart */}
											{industryList.length > 0 && (
												<div className="rounded-xl border border-white/10 bg-black/25 p-6 backdrop-blur-sm">
													<h4 className="mb-4 text-lg font-semibold text-[#fafafa]">Industry Distribution</h4>
													<div className="flex justify-center h-96">
														<div className="w-full max-w-md">
															<Pie
																data={industryChartData}
																options={summaryPieChartOptions}
																plugins={[pieDepthPlugin]}
															/>
														</div>
													</div>
													{/* Reasoning Cards */}
													<div className="mt-6 grid grid-cols-1 gap-3">
														{industryList.map((item: { name?: string; percentage: number; reasoning?: string }, index: number) => (
															<ReasoningCard
																key={index}
																label={item.name || ""}
																percentage={item.percentage}
																reasoning={item.reasoning}
															/>
														))}
													</div>
												</div>
											)}

											{/* Portfolio Allocation Chart */}
											{finalPortfolio.length > 0 && (
												<div className="rounded-xl border border-white/10 bg-black/25 p-6 backdrop-blur-sm">
													<h4 className="mb-4 text-lg font-semibold text-[#fafafa]">Portfolio Allocation</h4>
													<div className="flex justify-center h-96">
														<div className="w-full max-w-md">
															<Pie
																data={portfolioChartData}
																options={summaryPieChartOptions}
																plugins={[pieDepthPlugin]}
															/>
														</div>
													</div>
													{/* Reasoning Cards */}
													<div className="mt-6 grid grid-cols-1 gap-3">
														{finalPortfolio.map((item: { ticker?: string; percentage: number; reasoning?: string }, index: number) => (
															<ReasoningCard
																key={index}
																label={item.ticker || ""}
																percentage={item.percentage}
																reasoning={item.reasoning}
															/>
														))}
													</div>
												</div>
											)}
										</div>
									)}

									{/* Streaming events section inside the card */}
									<div className="flex-1 overflow-hidden">
										<h3 className="text-lg font-semibold mb-4 text-[#fafafa]">Live Pipeline Events</h3>
										<div className="max-h-[600px] overflow-y-auto">
											{events.length === 0 ? (
												<div className="text-white/60 text-sm">Waiting for events...</div>
											) : (
												<div className="space-y-4">
													{events.map((event) => (
														<div
															key={event.id}
															className="rounded-lg border border-white/10 bg-black/25 p-4 backdrop-blur-sm"
														>
															<pre className="text-xs text-white/90 whitespace-pre-wrap wrap-break-word font-mono">
																{JSON.stringify(event, null, 2)}
															</pre>
														</div>
													))}
												</div>
											)}
										</div>
									</div>
								</div>
							)}
						</div>
					</div>
				)}
			</Container>
		</div>
	)
}
