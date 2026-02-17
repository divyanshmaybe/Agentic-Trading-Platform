/**
 * Simple API client for making requests to the portfolio server.
 */

const PORTFOLIO_SERVER_URL = process.env.NEXT_PUBLIC_PORTFOLIO_SERVER_URL || "http://localhost:8000"

class ApiError extends Error {
  status: number
  data: unknown

  constructor(message: string, status: number, data?: unknown) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.data = data
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorData: unknown
    try {
      errorData = await response.json()
    } catch {
      errorData = await response.text()
    }
    throw new ApiError(
      `Request failed with status ${response.status}`,
      response.status,
      errorData
    )
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T
  }

  return response.json()
}

function getClientCookie(name: string): string | null {
  if (typeof document === "undefined") return null
  const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`))
  return match ? match[2] : null
}

function getAuthHeaders(): HeadersInit {
  // Get token from cookie first, then localStorage (matching other frontend code)
  let token: string | null = null
  if (typeof window !== "undefined") {
    token = getClientCookie("access_token") || localStorage.getItem("access_token")
  }
  const headers: HeadersInit = {
    "Content-Type": "application/json",
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }
  return headers
}

export const apiClient = {
  async get<T>(path: string): Promise<T> {
    const response = await fetch(`${PORTFOLIO_SERVER_URL}${path}`, {
      method: "GET",
      headers: getAuthHeaders(),
      credentials: "include",
    })
    return handleResponse<T>(response)
  },

  async post<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${PORTFOLIO_SERVER_URL}${path}`, {
      method: "POST",
      headers: getAuthHeaders(),
      credentials: "include",
      body: body ? JSON.stringify(body) : undefined,
    })
    return handleResponse<T>(response)
  },

  async put<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${PORTFOLIO_SERVER_URL}${path}`, {
      method: "PUT",
      headers: getAuthHeaders(),
      credentials: "include",
      body: body ? JSON.stringify(body) : undefined,
    })
    return handleResponse<T>(response)
  },

  async patch<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${PORTFOLIO_SERVER_URL}${path}`, {
      method: "PATCH",
      headers: getAuthHeaders(),
      credentials: "include",
      body: body ? JSON.stringify(body) : undefined,
    })
    return handleResponse<T>(response)
  },

  async delete<T>(path: string): Promise<T> {
    const response = await fetch(`${PORTFOLIO_SERVER_URL}${path}`, {
      method: "DELETE",
      headers: getAuthHeaders(),
      credentials: "include",
    })
    return handleResponse<T>(response)
  },
}

export { ApiError }

