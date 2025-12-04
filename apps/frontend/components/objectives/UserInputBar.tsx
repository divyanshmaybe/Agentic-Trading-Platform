"use client"

import { useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Upload } from "lucide-react"
import { cn } from "@/lib/utils"

type UserInputBarProps = {
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

export function UserInputBar({
  onSend,
  disabled = false,
  placeholder = "Type your message or upload a .txt file...",
}: UserInputBarProps) {
  const [inputText, setInputText] = useState("")
  const [fileName, setFileName] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    if (!file.name.endsWith(".txt")) {
      alert("Please upload a .txt file only")
      return
    }

    try {
      const text = await file.text()
      setInputText(text)
      setFileName(file.name)
    } catch (error) {
      alert("Error reading file. Please try again.")
      console.error("File read error:", error)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!inputText.trim() || disabled) return

    onSend(inputText.trim())
    setInputText("")
    setFileName(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2 items-end">
      <div className="flex-1 flex flex-col gap-2">
        <div className="relative">
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            disabled={disabled}
            placeholder={placeholder}
            className={cn(
              "w-full rounded-lg border border-white/15 bg-white/8 px-4 py-3",
              "text-[#fafafa] placeholder:text-white/40",
              "focus:outline-none focus:ring-2 focus:ring-white/20 focus:border-white/30",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              "transition-all"
            )}
          />
          {fileName && (
            <div className="absolute -top-6 left-0 text-xs text-white/60">
              File: {fileName}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt"
            onChange={handleFileChange}
            disabled={disabled}
            className="hidden"
            id="file-upload"
          />
          <label
            htmlFor="file-upload"
            className={cn(
              "flex items-center gap-2 px-3 py-2 rounded-md",
              "border border-white/15 bg-white/8 text-white/80",
              "hover:bg-white/10 hover:border-white/25 cursor-pointer",
              "transition-all text-sm",
              disabled && "opacity-50 cursor-not-allowed"
            )}
          >
            <Upload size={16} />
            <span>Upload .txt</span>
          </label>
        </div>
      </div>
      <Button
        type="submit"
        disabled={!inputText.trim() || disabled}
        className="h-11 px-6 bg-white/10 hover:bg-white/20 text-[#fafafa] border border-white/15"
      >
        Send
      </Button>
    </form>
  )
}

