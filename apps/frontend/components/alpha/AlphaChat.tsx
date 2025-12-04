"use client"

import { useState } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { Beaker, BookOpen, ChevronDown, ChevronUp, Rocket, Sparkles, Zap } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

// Tutorial steps for the workflow
const tutorialSteps = [
  {
    step: 1,
    title: "Form a Hypothesis",
    icon: BookOpen,
    description: "Start with a market observation or trading idea you want to test.",
    example: "Stocks breaking out of 20-day highs with increasing volume tend to continue upward.",
  },
  {
    step: 2,
    title: "Run Research",
    icon: Beaker,
    description: "Click 'New Research' to let AI generate factor expressions and backtest them.",
    example: "The system will create factors like DELTA($close, 20), $volume/SMA($volume, 20), etc.",
  },
  {
    step: 3,
    title: "Analyze Results",
    icon: Zap,
    description: "Review metrics like Sharpe Ratio, IC, and returns. Iterate to improve.",
    example: "If Sharpe < 1.5, try adjusting the hypothesis or adding risk constraints.",
  },
  {
    step: 4,
    title: "Deploy Live",
    icon: Rocket,
    description: "Once satisfied with backtests, deploy the alpha to generate daily signals.",
    example: "Allocate capital and the system will stream real-time trading signals.",
  },
]

type AlphaChatProps = {
  className?: string
}

// Collapsible tutorial step component
function TutorialStep({ step, isExpanded, onToggle }: { 
  step: typeof tutorialSteps[0]
  isExpanded: boolean
  onToggle: () => void 
}) {
  const Icon = step.icon
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 overflow-hidden">
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-white/5 transition"
      >
        <div className="flex size-6 items-center justify-center rounded-full bg-violet-500/20 text-violet-300 text-xs font-bold">
          {step.step}
        </div>
        <Icon className="size-4 text-violet-400" />
        <span className="flex-1 text-sm font-medium text-white/90">{step.title}</span>
        {isExpanded ? (
          <ChevronUp className="size-4 text-white/40" />
        ) : (
          <ChevronDown className="size-4 text-white/40" />
        )}
      </button>
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="border-t border-white/5 px-3 py-3 space-y-2">
              <p className="text-xs text-white/60">{step.description}</p>
              <div className="rounded-md bg-black/30 px-2.5 py-2">
                <p className="text-[11px] text-cyan-300/80 font-mono">{step.example}</p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function AlphaChat({ className }: AlphaChatProps) {
  const [expandedStep, setExpandedStep] = useState<number | null>(null)

  return (
    <Card
      className={cn(
        "card-glass flex h-full flex-col rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_28px_65px_-38px_rgba(0,0,0,0.9)] backdrop-blur",
        className
      )}
    >
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-2xl font-playfair text-[#fafafa]">
          <Sparkles className="size-5 text-violet-400" />
          Alpha Research Guide
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col overflow-hidden">
        {/* Tutorial Steps */}
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-wider text-white/40 mb-3">Workflow Steps</p>
          {tutorialSteps.map((step) => (
            <TutorialStep
              key={step.step}
              step={step}
              isExpanded={expandedStep === step.step}
              onToggle={() => setExpandedStep(expandedStep === step.step ? null : step.step)}
            />
          ))}
        </div>

        {/* Quick Tips */}
        <div className="mt-6 rounded-xl border border-white/10 bg-black/25 p-4">
          <p className="text-xs uppercase tracking-wider text-white/40 mb-3">Quick Tips</p>
          <ul className="space-y-2 text-xs text-white/60">
            <li className="flex items-start gap-2">
              <span className="text-violet-400">•</span>
              <span>Start simple — test one idea at a time before combining factors</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-violet-400">•</span>
              <span>Look for <span className="text-cyan-300">Sharpe &gt; 1.5</span> and consistent IC across train/test</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-violet-400">•</span>
              <span>Use <span className="text-cyan-300">3+ iterations</span> for thorough factor optimization</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-violet-400">•</span>
              <span>Deploy with small capital first to validate live performance</span>
            </li>
          </ul>
        </div>
      </CardContent>
    </Card>
  )
}
