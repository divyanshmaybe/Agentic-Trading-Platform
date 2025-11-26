"use client"

import { FormEvent, useState } from "react"
import { createPortal } from "react-dom"
import { AnimatePresence, motion } from "framer-motion"
import { Plus, X } from "lucide-react"
import { useParams } from "next/navigation"

import { AlphaChat, AlphaGraph, TopAlphas } from "@/components/alpha"
import { AgentOverview } from "@/components/agent/AgentOverview"
import { AgentTradesTable } from "@/components/agent/AgentTradesTable"
import { DashboardHeader } from "@/components/dashboard/DashboardHeader"
import { Container } from "@/components/shared/Container"
import { PageHeading } from "@/components/shared/PageHeading"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/useAuth"
import { useAgentDashboard } from "@/hooks/useAgentDashboard"

type AddAlphaForm = {
  name: string
  formula: string
  description: string
}

const emptyForm: AddAlphaForm = {
  name: "",
  formula: "",
  description: "",
}

function AddAlphaModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [form, setForm] = useState<AddAlphaForm>(emptyForm)
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState<string | null>(null)

  function resetState() {
    setForm(emptyForm)
    setSubmitting(false)
    setSuccess(null)
  }

  const handleClose = () => {
    resetState()
    onOpenChange(false)
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setTimeout(() => {
      setSuccess("Alpha submitted for review. Our team will backtest it shortly.")
      setSubmitting(false)
      setTimeout(() => {
        handleClose()
      }, 1200)
    }, 800)
  }

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-100 flex items-center justify-center bg-black/70 backdrop-blur"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.div
            initial={{ opacity: 0, y: 40, scale: 0.92 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.96 }}
            transition={{ type: "spring", stiffness: 260, damping: 26 }}
            className="mx-4 w-full max-w-xl rounded-2xl border border-white/10 bg-black/85 p-6 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-white">Add Your Own Alpha</h2>
                <p className="mt-1 text-sm text-white/60">
                  Share your strategy idea and we&apos;ll simulate its performance.
                </p>
              </div>
              <button
                type="button"
                onClick={handleClose}
                className="rounded-full border border-white/10 bg-white/5 p-1.5 text-white/70 transition hover:bg-white/10 hover:text-white"
              >
                <X className="size-4" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="mt-6 space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs uppercase tracking-wide text-white/50">Alpha Name</label>
                <input
                  value={form.name}
                  onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                  required
                  placeholder="Short Gamma Mean Revert"
                  className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs uppercase tracking-wide text-white/50">Formula / Logic</label>
                <textarea
                  value={form.formula}
                  onChange={(event) => setForm((prev) => ({ ...prev, formula: event.target.value }))}
                  required
                  rows={3}
                  placeholder="(RSI(14) < 30) AND (MACD_hist > 0) AND (Volume > 1.5x 20d avg)"
                  className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs uppercase tracking-wide text-white/50">Description</label>
                <textarea
                  value={form.description}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, description: event.target.value }))
                  }
                  rows={3}
                  placeholder="Notes about universe, timeframes, exits, risk limits..."
                  className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-sm text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
                />
              </div>

              {success ? (
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
                  {success}
                </div>
              ) : null}

              <div className="flex justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleClose}
                  className="border-white/20 text-white hover:bg-white/10"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  className="border border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
                  disabled={submitting}
                >
                  {submitting ? "Submitting..." : "Submit Alpha"}
                </Button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}

export default function AlphasPage() {
  const params = useParams()
  const username = params.username as string
  const [modalOpen, setModalOpen] = useState(false)

  // SECURE: Get user data from server-validated token, NOT localStorage
  const { user: authUser, loading: authLoading } = useAuth()
  
  // Fetch alpha agent dashboard data
  const { data: alphaData, loading: alphaLoading, isAllocating: alphaAllocating } = useAgentDashboard("alpha")

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

      <main className="lg:pr-96">
        <Container className="no-scrollbar max-w-10xl space-y-6 py-8 lg:max-h-[calc(100vh-4rem)] lg:overflow-y-auto">
          <PageHeading
            tagline="Monitor performance, iterate ideas, and deploy your next winning alpha."
            title="Alpha Command Center"
            action={
              <Button
                onClick={() => setModalOpen(true)}
                className="border border-emerald-500/40 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
              >
                <Plus className="mr-2 size-4" />
                Add Your Own Alpha
              </Button>
            }
          />

          <div className="flex flex-col gap-6">
            <div className="grid gap-6 lg:grid-cols-2">
              <AgentOverview data={alphaData} loading={alphaLoading} isAllocating={alphaAllocating} />
              <TopAlphas />
            </div>
            <AlphaGraph />
            <AgentTradesTable trades={alphaData?.recent_trades || []} loading={alphaLoading} />

            <div className="lg:hidden">
              <div className="mt-6">
                <AlphaChat />
              </div>
            </div>
          </div>
        </Container>
      </main>

      <aside className="fixed right-0 top-16 hidden h-[calc(100vh-4rem)] w-[24rem] flex-col border-l border-white/10 bg-[#070707]/95 shadow-2xl backdrop-blur-lg lg:flex">
        <AlphaChat className="flex-1 overflow-hidden" />
      </aside>

      <AddAlphaModal open={modalOpen} onOpenChange={setModalOpen} />
    </div>
  )
}
