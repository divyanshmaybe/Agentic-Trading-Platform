"use client"

import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { LoadingState } from "@/components/objectives/LoadingState"
import { ChatContainer } from "@/components/objectives/ChatContainer"
import { UserInputBar } from "@/components/objectives/UserInputBar"
import { ObjectiveDashboard } from "@/components/objectives/ObjectiveDashboard"
import { RequiredFieldsForm } from "@/components/objectives/RequiredFieldsForm"
import { useAuth } from "@/hooks/useAuth"
import { useObjectiveFields } from "@/hooks/useObjectiveFields"
import { useObjectiveChat } from "@/hooks/useObjectiveChat"
import { useObjectives } from "@/hooks/useObjectives"
import { useParams } from "next/navigation"
import { ObservabilityDashboard } from "@/components/observability/ObservabilityDashboard"

export default function ObjectivesPage() {
	const params = useParams()
	const username = params.username as string
	const { user: authUser, loading: authLoading } = useAuth()

	if (authLoading || !authUser) {
		return <LoadingState />
	}

	return (
		<div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
			<DashboardHeader
				userName={authUser.firstName}
				username={username}
				userRole={authUser.role}
			/>
			<Container className="max-w-7xl space-y-6 py-8">
				<PageHeading
					title="Observability"
					tagline="Monitor and analyze your trading objectives and goals"
				/>
				<ObservabilityDashboard />
			</Container>
		</div>
	)
}
