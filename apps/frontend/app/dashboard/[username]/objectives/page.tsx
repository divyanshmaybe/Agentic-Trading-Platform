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

export default function ObjectivesPage() {
  const params = useParams()
  const username = params.username as string
  const { user: authUser, loading: authLoading } = useAuth()
  const { activeObjective, loading: objectivesLoading, error: objectivesError } = useObjectives()

  const fieldHelpers = useObjectiveFields()
  const {
    messages,
    isProcessing,
    lastResponse,
    handleSend,
    handleFieldSubmit,
    setObjectiveName,
    setUserAge,
    objectiveName,
    userAge,
  } = useObjectiveChat(fieldHelpers)

  if (authLoading || !authUser) {
    return <LoadingState />
  }

  if (objectivesLoading) {
    return (
      <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
        <DashboardHeader
          userName={authUser.firstName}
          username={username}
          userRole={authUser.role}
        />
        <Container className="max-w-6xl space-y-6 py-8">
          <PageHeading
            title="Objectives"
            tagline="Manage your trading objectives and goals."
          />
          <LoadingState />
        </Container>
      </div>
    )
  }

  if (objectivesError) {
    return (
      <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
        <DashboardHeader
          userName={authUser.firstName}
          username={username}
          userRole={authUser.role}
        />
        <Container className="max-w-6xl space-y-6 py-8">
          <PageHeading
            title="Objectives"
            tagline="Manage your trading objectives and goals."
          />
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">
            Error loading objectives: {objectivesError}
          </div>
        </Container>
      </div>
    )
  }

  // If objective exists, show dashboard
  if (activeObjective) {
    return (
      <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
        <DashboardHeader
          userName={authUser.firstName}
          username={username}
          userRole={authUser.role}
        />
        <Container className="max-w-6xl space-y-6 py-8">
          <PageHeading
            title="Objectives"
            tagline="Manage your trading objectives and goals."
          />
          <ObjectiveDashboard objective={activeObjective} />
        </Container>
      </div>
    )
  }

  // If no objective exists, show chat interface
  const currentField = fieldHelpers.getCurrentField(lastResponse)
  const showFieldInput = currentField && !isProcessing

  return (
    <div className="min-h-screen bg-[#0c0c0c] text-[#fafafa]">
      <DashboardHeader
        userName={authUser.firstName}
        username={username}
        userRole={authUser.role}
      />
      <Container className="max-w-6xl space-y-6 py-8">
        <PageHeading
          title="Objectives"
          tagline="Manage your trading objectives and goals."
        />

        <RequiredFieldsForm
          onFieldsChange={(name, age) => {
            setObjectiveName(name)
            setUserAge(age)
          }}
          disabled={isProcessing}
        />

        <div className="flex flex-col h-[calc(100vh-400px)] border border-white/10 rounded-lg bg-white/6 backdrop-blur overflow-hidden">
          <ChatContainer
            messages={messages}
            isProcessing={isProcessing}
            currentField={currentField}
            onFieldSubmit={handleFieldSubmit}
          />

          <div className="border-t border-white/10 p-4 bg-white/8">
            <UserInputBar
              onSend={handleSend}
              disabled={isProcessing || !!showFieldInput || !objectiveName.trim() || !userAge}
              placeholder={
                !objectiveName.trim() || !userAge
                  ? "Please fill in the required fields above first..."
                  : showFieldInput
                  ? "Please complete the field above first..."
                  : "Type your message or upload a .txt file..."
              }
            />
          </div>
        </div>
      </Container>
    </div>
  )
}

