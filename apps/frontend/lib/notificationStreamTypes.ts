export type NotificationStreamAction = {
  label: string
  value: string
  href?: string
}

export type NotificationStreamItem = {
  id: string
  type: string
  topic?: string
  timestamp?: string
  data?: Record<string, unknown>
  actions?: NotificationStreamAction[]
  title?: string
  body?: string
}
