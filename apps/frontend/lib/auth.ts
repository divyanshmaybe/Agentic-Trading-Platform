export type RegisterOrganizationPayload = {
  name: string
  email: string
  phone?: string
  address?: string
  registration_number?: string
  tax_id?: string
  admin: {
    email: string
    password: string
    first_name: string
    last_name: string
  }
}

export type RegisterOrganizationResponse = {
  success: boolean
  data: {
    organization: {
      id: string
      name: string
      email: string
      status: string
    }
    admin: {
      id: string
      email: string
      role: string
    }
    access_token: string
    refresh_token: string
  }
}

export type LoginPayload = {
  email: string
  password: string
  organization_id?: string
}

export type LoginResponse = {
  success: boolean
  data: {
    user: {
      id: string
      role: string
      email: string
      first_name: string
      last_name: string
      organization_id: string
    }
    access_token: string
    refresh_token: string
  }
}

type AuthApiError = {
  success?: boolean
  message?: string
  error?: string
  errors?: Record<string, string[]> | string
}

const AUTH_BASE_URL =
  process.env.NEXT_PUBLIC_AUTH_BASE_URL ?? "http://localhost:4000/api/auth"

async function request<T>(path: string, options: RequestInit): Promise<T> {
  const response = await fetch(`${AUTH_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    credentials: "include",
  })

  const isJson = response.headers
    .get("content-type")
    ?.includes("application/json")

  const body = isJson ? await response.json() : null

  if (!response.ok) {
    const error: AuthApiError = body ?? {}

    const errorsFromObject =
      error.errors && typeof error.errors === "object" && !Array.isArray(error.errors)
        ? Object.values(error.errors)
            .flat()
            .join(", ")
        : undefined

    const message =
      (typeof error.errors === "string" && error.errors) ||
      (Array.isArray(error.errors) ? error.errors.join(", ") : undefined) ||
      errorsFromObject ||
      error.message ||
      (typeof body === "string" ? body : undefined) ||
      response.statusText
    throw new Error(message || "Request failed")
  }

  return body as T
}

export async function registerOrganization(payload: RegisterOrganizationPayload) {
  return request<RegisterOrganizationResponse>("/organizations/register", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function login(payload: LoginPayload) {
  return request<LoginResponse>("/login", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export type { AuthApiError }
