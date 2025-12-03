"use client"

import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { LoadingState } from "@/components/objectives/LoadingState"
import { ChatContainer } from "@/components/objectives/ChatContainer"
import { UserInputBar } from "@/components/objectives/UserInputBar"
import { useAuth } from "@/hooks/useAuth"
import { useObjectiveFields } from "@/hooks/useObjectiveFields"
import { useObjectiveChat } from "@/hooks/useObjectiveChat"
import { useParams } from "next/navigation"

export default function ObjectivesPage() {
  const params = useParams()
  const username = params.username as string
  const { user: authUser, loading: authLoading } = useAuth()

  const fieldHelpers = useObjectiveFields()
  const { messages, isProcessing, lastResponse, handleSend, handleFieldSubmit } = useObjectiveChat(fieldHelpers)

  if (authLoading || !authUser) {
    return <LoadingState />
  }

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

        <div className="flex flex-col h-[calc(100vh-250px)] border border-white/10 rounded-lg bg-black/20 overflow-hidden">
          <ChatContainer
            messages={messages}
            isProcessing={isProcessing}
            currentField={currentField}
            onFieldSubmit={handleFieldSubmit}
          />

          <div className="border-t border-white/10 p-4 bg-black/30">
            <UserInputBar
              onSend={handleSend}
              disabled={isProcessing || !!showFieldInput}
              placeholder={
                showFieldInput
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

