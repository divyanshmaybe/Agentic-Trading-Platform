export type KafkaNotificationAction = {
  label: string
  value: string
  href?: string
}

export type KafkaNotification = {
  id: string
  type: string
  topic?: string
  timestamp?: string
  data?: Record<string, unknown>
  actions?: KafkaNotificationAction[]
  title?: string
  body?: string
}
2