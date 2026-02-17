"use client"

import { useEffect, useState } from "react"
import { createPortal } from "react-dom"
import type { FormEventHandler } from "react"
import type { FieldErrors, UseFormRegister } from "react-hook-form"
import { AnimatePresence, motion } from "framer-motion"
import { X } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

import { CreateUserForm } from "./CreateUserForm"
import type { CreateUserFormValues } from "./types"

type CreateUserModalProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title?: string
  register: UseFormRegister<CreateUserFormValues>
  errors: FieldErrors<CreateUserFormValues>
  onSubmit: FormEventHandler<HTMLFormElement>
  isSubmitting: boolean
  errorMessage?: string | null
  successMessage?: string | null
}

export function CreateUserModal({
  open,
  onOpenChange,
  title = "Create User",
  register,
  errors,
  onSubmit,
  isSubmitting,
  errorMessage,
  successMessage,
}: CreateUserModalProps) {
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    if (!open) return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onOpenChange(false)
      }
    }

    window.addEventListener("keydown", handleKeyDown)

    return () => {
      window.removeEventListener("keydown", handleKeyDown)
    }
  }, [open, onOpenChange])

  useEffect(() => {
    if (!open) {
      document.body.style.removeProperty("overflow")
      return
    }

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"

    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [open])

  if (!mounted) {
    return null
  }

  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.div
            className="mx-4 w-full max-w-lg"
            initial={{ scale: 0.92, opacity: 0, y: 40 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: 24 }}
            transition={{ type: "spring", stiffness: 260, damping: 24 }}
          >
            <Card className="card-glass rounded-2xl border border-white/10 bg-black/80 text-white shadow-2xl">
              <CardHeader className="flex flex-row items-start justify-between gap-4">
                <div>
                  <CardTitle className="h-title text-xl">{title}</CardTitle>
                  <p className="mt-1 text-sm text-white/60">
                    Provide details below to onboard a new team member or customer.
                  </p>
                </div>
                <button
                  type="button"
                  className="rounded-full border border-white/10 bg-white/5 p-1.5 text-white/70 transition hover:bg-white/10 hover:text-white"
                  onClick={() => onOpenChange(false)}
                  aria-label="Close create user modal"
                >
                  <X className="size-4" />
                </button>
              </CardHeader>
              <CardContent className="pt-0">
                <CreateUserForm
                  register={register}
                  errors={errors}
                  onSubmit={onSubmit}
                  isSubmitting={isSubmitting}
                  errorMessage={errorMessage}
                  successMessage={successMessage}
                />
              </CardContent>
            </Card>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  )
}

