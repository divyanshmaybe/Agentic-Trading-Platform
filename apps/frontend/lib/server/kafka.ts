import { readFileSync } from "node:fs"
import { randomUUID } from "node:crypto"

import { Kafka, logLevel, type SASLOptions } from "kafkajs"

const GLOBAL_CLIENT_KEY = "__AGENTIC_FRONTEND_KAFKA_CLIENT__"

type KafkaClientCache = {
  [GLOBAL_CLIENT_KEY]?: Kafka
}

type SupportedMechanism = "plain" | "scram-sha-256" | "scram-sha-512" | "aws" | "oauthbearer"

function getGlobalCache(): KafkaClientCache {
  return globalThis as typeof globalThis & KafkaClientCache
}

function normaliseSaslMechanism(mechanism: string): SupportedMechanism {
  const normalised = mechanism.trim().toLowerCase().replace(/_/g, "-")
  switch (normalised) {
    case "plain":
      return "plain"
    case "scram-sha-256":
      return "scram-sha-256"
    case "scram-sha-512":
      return "scram-sha-512"
    case "aws":
      return "aws"
    case "oauthbearer":
      return "oauthbearer"
    default:
      throw new Error(`Unsupported SASL mechanism "${mechanism}" for Kafka consumer`)
  }
}

function buildKafkaClient(): Kafka {
  const fallbackBootstrap = "localhost:9092"
  const configuredBootstrap = process.env.KAFKA_BOOTSTRAP_SERVERS?.trim()
  const bootstrapSource = configuredBootstrap && configuredBootstrap.length > 0 ? configuredBootstrap : fallbackBootstrap

  if (!configuredBootstrap) {
    console.warn(`[Kafka] KAFKA_BOOTSTRAP_SERVERS not set; defaulting to ${fallbackBootstrap}`)
  }

  const bootstrapServers = bootstrapSource

  const brokers = bootstrapServers
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean)

  if (!brokers.length) {
    throw new Error("KAFKA_BOOTSTRAP_SERVERS does not contain any valid brokers")
  }

  const clientId = process.env.KAFKA_CLIENT_ID ?? "frontend-notifications"
  const kafkaConfig: ConstructorParameters<typeof Kafka>[0] = {
    clientId,
    brokers,
    logLevel: logLevel.NOTHING,
    retry: {
      retries: 3,
      initialRetryTime: 100,
      multiplier: 2,
      maxRetryTime: 30000,
    },
    connectionTimeout: 3000,
    requestTimeout: 30000,
  }

  const securityProtocol = process.env.KAFKA_SECURITY_PROTOCOL?.toUpperCase()
  if (securityProtocol?.includes("SSL")) {
    const caFile = process.env.KAFKA_SSL_CAFILE
    if (caFile) {
      try {
        const caCert = readFileSync(caFile, "utf8")
        kafkaConfig.ssl = { ca: [caCert] }
      } catch (err) {
        console.warn(`[Kafka] Failed to read CA file ${caFile}:`, err)
        kafkaConfig.ssl = true
      }
    } else {
      kafkaConfig.ssl = true
    }
  }

  const saslMechanism = process.env.KAFKA_SASL_MECHANISM
  const saslUsername = process.env.KAFKA_SASL_USERNAME
  const saslPassword = process.env.KAFKA_SASL_PASSWORD

  if (saslMechanism && saslUsername && saslPassword) {
    kafkaConfig.sasl = {
      mechanism: normaliseSaslMechanism(saslMechanism),
      username: saslUsername,
      password: saslPassword,
    } as SASLOptions
  }

  return new Kafka(kafkaConfig)
}

export function getKafkaClient(): Kafka {
  const cache = getGlobalCache()
  if (!cache[GLOBAL_CLIENT_KEY]) {
    cache[GLOBAL_CLIENT_KEY] = buildKafkaClient()
  }
  return cache[GLOBAL_CLIENT_KEY]!
}

export function createNotificationConsumer(groupId?: string) {
  const kafka = getKafkaClient()
  return kafka.consumer({
    groupId: groupId ?? `frontend-low-risk-${randomUUID()}`,
    allowAutoTopicCreation: false,
    sessionTimeout: 30000,
    heartbeatInterval: 3000,
    maxInFlightRequests: 1,
  })
}

