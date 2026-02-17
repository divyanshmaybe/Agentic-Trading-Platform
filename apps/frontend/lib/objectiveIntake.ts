/**
 * Objective Intake API Client
 *
 * Handles investment objective submission and AI trading subscription management.
 * Transcript parsing is handled by the backend using Gemini 2.5 Flash.
 */

// -----------------------------------------------------------------------------
// Type Definitions
// -----------------------------------------------------------------------------

export type ObjectiveIntakeRequest = {
  objective_id?: string | null
  name?: string | null
  transcript?: string | null
  structured_payload?: Record<string, any> | null
  metadata?: Record<string, any> | null
  source?: string | null
}

export type AllocationResultSummary = {
  weights?: Record<string, number>
  expected_return?: number | null
  expected_risk?: number | null
  objective_value?: number | null
  message?: string | null
  regime?: string | null
  progress_ratio?: number | null
}

export type ObjectiveIntakeResponse = {
  objective_id: string
  status: "pending" | "complete"
  missing_fields: string[]
  structured_payload: Record<string, any>
  warnings: string[]
  message?: string | null
  created: boolean
  completion_timestamp?: string | null
  allocation?: AllocationResultSummary | null
}

export type ObjectiveResponse = {
  id: string
  user_id: string
  name?: string | null
  raw?: Record<string, any> | null
  source?: string | null
  structured_payload?: Record<string, any> | null
  investable_amount?: string | number | null
  investment_horizon_years?: number | null
  investment_horizon_label?: string | null
  target_return?: string | number | null
  risk_tolerance?: string | null
  risk_aversion_lambda?: string | number | null
  liquidity_needs?: string | null
  rebalancing_frequency?: string | null
  constraints?: Record<string, any> | null
  target_returns?: any[] | null
  preferences?: Record<string, any> | null
  generic_notes?: string[] | any[] | null
  missing_fields?: string[] | null
  completion_status: string
  status: string
  created_at: string
  updated_at: string
}

export type FieldType = "number" | "text" | "select"

type ApiError = {
  detail?: string
  message?: string
  error?: string
}

// -----------------------------------------------------------------------------
// Constants
// -----------------------------------------------------------------------------

const PORTFOLIO_BASE_URL =
  process.env.NEXT_PUBLIC_PORTFOLIO_API_URL ?? "http://localhost:8000"

const FIELD_TYPE_MAP: Record<string, FieldType> = {
  investable_amount: "number",
  target_return: "number",
  investment_horizon: "text",
  "risk_tolerance.category": "select",
  liquidity_needs: "select",
}

const FIELD_ALLOWED_VALUES: Record<string, string[]> = {
  "risk_tolerance.category": ["low", "medium", "high"],
  liquidity_needs: ["immediate", "3-12 months", "long"],
}

// -----------------------------------------------------------------------------
// Auth Helpers
// -----------------------------------------------------------------------------

function getClientCookie(name: string): string | null {
  if (typeof document === "undefined") return null

  const entry = document.cookie
    .split(";")
    .map((s) => s.trim())
    .find((s) => s.startsWith(`${name}=`))

  if (!entry) return null
  const [, value] = entry.split("=")
  return value ? decodeURIComponent(value) : null
}

function resolveAccessToken(explicitToken?: string): string {
  if (explicitToken) return explicitToken

  if (typeof window !== "undefined") {
    const cookieToken = getClientCookie("access_token")
    if (cookieToken) return cookieToken

    const storedToken = localStorage.getItem("access_token")
    if (storedToken) return storedToken
  }

  throw new Error("Missing access token. Please log in again.")
}

// -----------------------------------------------------------------------------
// API Client
// -----------------------------------------------------------------------------

async function request<T>(path: string, options: RequestInit): Promise<T> {
  const response = await fetch(`${PORTFOLIO_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  })

  const isJson = response.headers
    .get("content-type")
    ?.includes("application/json")
  const body = isJson ? await response.json() : null

  if (!response.ok) {
    const error: ApiError = body ?? {}
    const message =
      error.detail ||
      error.message ||
      error.error ||
      (typeof body === "string" ? body : undefined) ||
      response.statusText

    // Handle unauthorized - redirect to login
    if (response.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("access_token")
      localStorage.removeItem("refresh_token")
      window.location.href = "/login"
    }

    throw new Error(message || "Request failed")
  }

  return body as T
}

// -----------------------------------------------------------------------------
// Public API
// -----------------------------------------------------------------------------

/**
 * Submit an objective intake request.
 * Transcript is parsed by the backend using Gemini 2.5 Flash.
 */
export async function submitObjectiveIntake(
  payload: ObjectiveIntakeRequest,
  accessToken?: string
): Promise<ObjectiveIntakeResponse> {
  const token = resolveAccessToken(accessToken)

  return request<ObjectiveIntakeResponse>("/api/objectives/intake", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export async function fetchObjectives(
  accessToken?: string,
  status?: string,
  includeInactive?: boolean
): Promise<ObjectiveResponse[]> {
  const token = resolveAccessToken(accessToken)

  const params = new URLSearchParams()
  if (status) {
    params.append("status", status)
  }
  if (includeInactive !== undefined) {
    params.append("include_inactive", includeInactive.toString())
  }

  const queryString = params.toString()
  const path = `/api/objectives/${queryString ? `?${queryString}` : ""}`

  return request<ObjectiveResponse[]>(path, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export async function enableAITradingSubscription(
  accessToken?: string
): Promise<{ success: boolean; message?: string }> {
  try {
    const { updateUserSubscription } = await import("@/lib/auth")
    const agents = ["high_risk", "low_risk", "alpha", "liquid"] as const

    await Promise.all(
      agents.map((agent) =>
        updateUserSubscription({ action: "subscribe", agent }, accessToken)
      )
    )

    return {
      success: true,
      message: "AI trading subscriptions enabled for all agents",
    }
  } catch (error) {
    return {
      success: false,
      message:
        error instanceof Error
          ? error.message
          : "Failed to enable AI trading subscription",
    }
  }
}

// -----------------------------------------------------------------------------
// Field Utilities
// -----------------------------------------------------------------------------

export function inferFieldType(fieldName: string): FieldType {
  return FIELD_TYPE_MAP[fieldName] ?? "text"
}

export function getAllowedValues(fieldName: string): string[] | null {
  return FIELD_ALLOWED_VALUES[fieldName] ?? null
}

export function formatFieldName(fieldName: string): string {
  const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

  if (fieldName.includes(".")) {
    return fieldName.split(".").map(capitalize).join(" ")
  }

  return fieldName.split("_").map(capitalize).join(" ")
}