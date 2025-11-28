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
    user: {
      id: string
      email: string
      first_name: string
      last_name: string
      role: string
      organization_id: string
      username: string
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
      role: UserRole
      email: string
      first_name: string
      last_name: string
      organization_id: string
      username: string
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

export type CreateUserPayload = {
  email: string
  password: string
  first_name: string
  last_name: string
  role: "staff" | "viewer" | "customer"
}

export type CreateUserResponse = {
  success: boolean
  data: {
    id: string
    role: string
    email: string
    first_name: string
    last_name: string
    username: string
  }
}

export type UserRole = "admin" | "staff" | "viewer"

export type UserStatus = "active" | "suspended" | "inactive"

export type AuthUserSummary = {
  id: string
  email: string
  first_name: string
  last_name: string
  phone: string | null
  role: UserRole
  status: UserStatus
  last_login_at: string | null
  two_factor_enabled: boolean
  created_at: string
  updated_at: string
}

export type GetUsersParams = {
  role?: UserRole
  status?: UserStatus
  search?: string
  page?: number
  limit?: number
}

export type GetUsersResponse = {
  success: boolean
  data: {
    users: AuthUserSummary[]
    pagination: {
      page: number
      limit: number
      total: number
      totalPages: number
      hasNextPage: boolean
      hasPrevPage: boolean
    }
    filters: {
      role: UserRole | null
      status: UserStatus | null
      search: string | null
    }
  }
}

export type UpdateUserPayload = {
  role?: UserRole
  status?: UserStatus
}

export type UpdateUserResponse = {
  success: boolean
  data: AuthUserSummary
}

const AUTH_BASE_URL =
  process.env.NEXT_PUBLIC_AUTH_BASE_URL ?? "http://localhost:4000/api/auth"

function getClientCookie(name: string): string | null {
  if (typeof document === "undefined") return null
  const cookieString = document.cookie
  if (!cookieString) return null
  const entry = cookieString
    .split(";")
    .map((section) => section.trim())
    .find((section) => section.startsWith(`${name}=`))
  if (!entry) return null
  const [, value] = entry.split("=")
  return value ? decodeURIComponent(value) : null
}

function resolveAccessToken(explicitToken?: string) {
  if (explicitToken) return explicitToken
  if (typeof window !== "undefined") {
    const cookieToken = getClientCookie("access_token")
    if (cookieToken) return cookieToken
    const stored = localStorage.getItem("access_token")
    if (stored) return stored
  }
  throw new Error("Missing access token. Please log in again.")
}

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

export async function createUser(payload: CreateUserPayload, accessToken?: string) {
  const token = resolveAccessToken(accessToken)

  const normalizedPayload = {
    ...payload,
    role: payload.role === "customer" ? "viewer" : payload.role,
  }

  return request<CreateUserResponse>("/users", {
    method: "POST",
    body: JSON.stringify(normalizedPayload),
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export type { AuthApiError }

export async function getUsers(params: GetUsersParams = {}, accessToken?: string) {
  const token = resolveAccessToken(accessToken)

  const searchParams = new URLSearchParams()

  if (params.role) searchParams.set("role", params.role)
  if (params.status) searchParams.set("status", params.status)
  if (params.search) searchParams.set("search", params.search)
  if (params.page) searchParams.set("page", String(params.page))
  if (params.limit) searchParams.set("limit", String(params.limit))

  const query = searchParams.toString()
  const path = `/users${query ? `?${query}` : ""}`

  return request<GetUsersResponse>(path, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export async function updateUser(
  userId: string,
  payload: UpdateUserPayload,
  accessToken?: string,
) {
  const token = resolveAccessToken(accessToken)

  return request<UpdateUserResponse>(`/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export type UpdateSubscriptionPayload = {
  action: "subscribe" | "unsubscribe"
  agent: "high_risk" | "low_risk" | "alpha" | "liquid"
}

export type UpdateSubscriptionResponse = {
  success: boolean
  data: {
    id: string
    subscriptions: string[]
  }
}

export async function updateUserSubscription(
  payload: UpdateSubscriptionPayload,
  accessToken?: string,
): Promise<UpdateSubscriptionResponse> {
  const token = resolveAccessToken(accessToken)

  // User routes are mounted at /api/user, not /api/auth
  const authServerUrl = process.env.NEXT_PUBLIC_AUTH_BASE_URL 
    ? process.env.NEXT_PUBLIC_AUTH_BASE_URL.replace("/api/auth", "")
    : "http://localhost:4000"
  
  const response = await fetch(`${authServerUrl}/api/user/subscriptions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    credentials: "include",
    body: JSON.stringify(payload),
  })

  const isJson = response.headers
    .get("content-type")
    ?.includes("application/json")

  const body = isJson ? await response.json() : null

  if (!response.ok) {
    const error: AuthApiError = body ?? {}
    const message =
      error.message ||
      error.error ||
      (typeof body === "string" ? body : undefined) ||
      response.statusText
    throw new Error(message || "Request failed")
  }

  return body as UpdateSubscriptionResponse
}
