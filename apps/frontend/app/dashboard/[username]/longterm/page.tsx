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
	PipelineEventsToggle,
	PipelineEventsList,
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
										{!hasSummary && (
											<EmptyStateMessage
												message="Start your long-term investment journey with our automated low-risk pipeline. Build wealth steadily through carefully selected positions."
												showButton={true}
												onButtonClick={handleRunPipeline}
												buttonLabel="Run Pipeline"
											/>
										)}

										{/* Toggleable events section */}
										<div className="flex-1 w-full">
											<PipelineEventsToggle
												eventCount={events.length}
												isExpanded={showAllEvents}
												onToggle={() => setShowAllEvents(!showAllEvents)}
											/>

											{showAllEvents && <PipelineEventsList events={allEvents} />}

											{/* Pie Charts - shown when summary event exists */}
											{hasSummary && (industryList.length > 0 || finalPortfolio.length > 0) && (
												<div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-2 mt-6">
													<IndustryDistributionChart
														industryList={industryList}
														chartData={industryChartData}
													/>
													<PortfolioAllocationChart
														finalPortfolio={finalPortfolio}
														chartData={portfolioChartData}
													/>
												</div>
											)}
										</div>
									</div>
								) : (
									/* Show run pipeline button when no events */
									!hasSummary && (
										<EmptyStateMessage
											message="Start your long-term investment journey with our automated low-risk pipeline. Build wealth steadily through carefully selected positions."
											showButton={true}
											onButtonClick={handleRunPipeline}
											buttonLabel="Run Pipeline"
											buttonDisabled={streaming}
										/>
									)
								)
							) : (
								/* Streaming layout with events */
								<div className="flex flex-1 flex-col gap-6">
									{/* Top section with message */}
									{!hasSummary && (
										<div className="flex flex-col items-center gap-6">
											<p className="text-center text-white/70 text-lg max-w-2xl">
												Pipeline is running... Building your long-term investment portfolio.
											</p>
										</div>
									)}

									{/* Pie Charts - shown when summary event exists */}
									{hasSummary && (industryList.length > 0 || finalPortfolio.length > 0) && (
										<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
											<IndustryDistributionChart
												industryList={industryList}
												chartData={industryChartData}
											/>
											<PortfolioAllocationChart
												finalPortfolio={finalPortfolio}
												chartData={portfolioChartData}
											/>
										</div>
									)}

									{/* Streaming events section inside the card */}
									<StreamingEventsView events={events} />
								</div>
							)}
						</div>
					</div>
				)}
			</Container>
		</div>
	)
}
