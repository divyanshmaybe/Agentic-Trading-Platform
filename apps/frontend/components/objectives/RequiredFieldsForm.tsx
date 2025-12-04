"use client"

import { useState } from "react"

interface RequiredFieldsFormProps {
  onFieldsChange: (name: string, age: number | null) => void
  disabled?: boolean
}

export function RequiredFieldsForm({ onFieldsChange, disabled = false }: RequiredFieldsFormProps) {
  const [objectiveName, setObjectiveName] = useState("")
  const [age, setAge] = useState<string>("")

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    setObjectiveName(value)
    const ageNum = age ? parseInt(age, 10) : null
    onFieldsChange(value, ageNum)
  }

  const handleAgeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    setAge(value)
    const ageNum = value ? parseInt(value, 10) : null
    onFieldsChange(objectiveName, ageNum)
  }

  return (
    <div className="border border-white/10 rounded-lg bg-white/8 backdrop-blur p-4 space-y-4">
      <div className="text-sm font-medium text-white/90 mb-3">Required Information</div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <label htmlFor="objective-name" className="block text-sm text-white/80">
            Objective Name <span className="text-red-400">*</span>
          </label>
          <input
            id="objective-name"
            type="text"
            placeholder="e.g., Retirement Investment Goal"
            value={objectiveName}
            onChange={handleNameChange}
            disabled={disabled}
            className="w-full px-3 py-2 bg-white/8 border border-white/20 rounded-md text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-white/30 focus:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
          />
        </div>
        <div className="space-y-2">
          <label htmlFor="age" className="block text-sm text-white/80">
            Age <span className="text-red-400">*</span>
          </label>
          <input
            id="age"
            type="number"
            placeholder="e.g., 35"
            value={age}
            onChange={handleAgeChange}
            disabled={disabled}
            min="1"
            max="120"
            className="w-full px-3 py-2 bg-white/8 border border-white/20 rounded-md text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-white/30 focus:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
          />
        </div>
      </div>
    </div>
  )
}

