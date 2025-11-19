import { readFileSync } from "node:fs";
import { Kafka, logLevel, Consumer, EachMessagePayload, SASLOptions } from "kafkajs";
import { PrismaClient } from "@prisma/client";
import { notificationConfig } from "../../config";
import { NotificationPublisher } from "../redis/publisher";

type SupportedMechanism = "plain" | "scram-sha-256" | "scram-sha-512" | "aws" | "oauthbearer";

type NormalizedNotification = {
  kafkaKey: string;
  topic: string;
  category: "stock_recommendation" | "news_sentiment" | "filing_signal" | "sector_analysis";
  title?: string;
  summary?: string;
  symbol?: string;
  sector?: string;
  sentiment?: string;
  signal?: string;
  confidence?: number;
  url?: string;
  rawPayload: any;
  eventTime?: Date;
};

function normaliseSaslMechanism(mechanism: string): SupportedMechanism {
  const normalised = mechanism.trim().toLowerCase().replace(/_/g, "-");
  switch (normalised) {
    case "plain":
      return "plain";
    case "scram-sha-256":
      return "scram-sha-256";
    case "scram-sha-512":
      return "scram-sha-512";
    case "aws":
      return "aws";
    case "oauthbearer":
      return "oauthbearer";
    default:
      throw new Error(`Unsupported SASL mechanism "${mechanism}" for Kafka consumer`);
  }
}

function buildKafkaClient(): Kafka {
  const fallbackBootstrap = "localhost:9092";
  const configuredBootstrap = notificationConfig.KAFKA_BOOTSTRAP_SERVERS?.trim();
  const bootstrapSource = configuredBootstrap && configuredBootstrap.length > 0 ? configuredBootstrap : fallbackBootstrap;

  if (!configuredBootstrap) {
    console.warn(`[Kafka] KAFKA_BOOTSTRAP_SERVERS not set; defaulting to ${fallbackBootstrap}`);
  }

  const brokers = bootstrapSource
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);

  if (!brokers.length) {
    throw new Error("KAFKA_BOOTSTRAP_SERVERS does not contain any valid brokers");
  }

  const clientId = notificationConfig.KAFKA_CLIENT_ID || "notification-server";
  const kafkaConfig: ConstructorParameters<typeof Kafka>[0] = {
    clientId,
    brokers,
    logLevel: logLevel.INFO,
    retry: {
      retries: 3,
      initialRetryTime: 100,
      multiplier: 2,
      maxRetryTime: 30000,
    },
    connectionTimeout: 3000,
    requestTimeout: 30000,
  };

  const securityProtocol = process.env.KAFKA_SECURITY_PROTOCOL?.toUpperCase();
  if (securityProtocol?.includes("SSL")) {
    const caFile = process.env.KAFKA_SSL_CAFILE;
    if (caFile) {
      try {
        const caCert = readFileSync(caFile, "utf8");
        kafkaConfig.ssl = { ca: [caCert] };
      } catch (err) {
        console.warn(`[Kafka] Failed to read CA file ${caFile}:`, err);
        kafkaConfig.ssl = true;
      }
    } else {
      kafkaConfig.ssl = true;
    }
  }

  const saslMechanism = process.env.KAFKA_SASL_MECHANISM;
  const saslUsername = process.env.KAFKA_SASL_USERNAME;
  const saslPassword = process.env.KAFKA_SASL_PASSWORD;

  if (saslMechanism && saslUsername && saslPassword) {
    kafkaConfig.sasl = {
      mechanism: normaliseSaslMechanism(saslMechanism),
      username: saslUsername,
      password: saslPassword,
    } as SASLOptions;
  }

  return new Kafka(kafkaConfig);
}

function parseJsonSafely(value: string | Buffer | null | undefined): any {
  if (!value) return null;
  const str = typeof value === "string" ? value : value.toString("utf8");
  try {
    return JSON.parse(str);
  } catch {
    return null;
  }
}

function normalizePayload(payload: any): any {
  if ("value" in payload) {
    if (typeof payload.value === "string") {
      try {
        const parsed = JSON.parse(payload.value);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          if ("value" in parsed && typeof parsed.value === "string") {
            try {
              return JSON.parse(parsed.value);
            } catch {
              return parsed;
            }
          }
          return parsed;
        }
      } catch {
        // Not valid JSON, continue
      }
    } else if (payload.value && typeof payload.value === "object" && "value" in payload.value && typeof payload.value.value === "string") {
      try {
        return JSON.parse(payload.value.value);
      } catch {
        return payload.value;
      }
    }
  }
  return payload;
}

function parseDateTime(value: any): Date | undefined {
  if (!value) return undefined;
  if (value instanceof Date) return value;
  if (typeof value === "number") return new Date(value);
  if (typeof value === "string") {
    const parsed = new Date(value);
    if (!isNaN(parsed.getTime())) return parsed;
  }
  return undefined;
}

function normalizeStockRecommendation(
  topic: string,
  payload: any,
  partition: number,
  offset: string
): NormalizedNotification {
  const kafkaKey = `${topic}-${partition}-${offset}`;

  return {
    kafkaKey,
    topic,
    category: "stock_recommendation",
    title: payload.stock_name ? `Stock Recommendation: ${payload.stock_name}` : undefined,
    summary: payload.detailed_analysis || undefined,
    symbol: payload.stock_name || undefined,
    sector: payload.sector || undefined,
    signal: payload.trade_signal || undefined,
    url: payload.news_source_url || payload.news_source || undefined,
    rawPayload: payload,
    eventTime: parseDateTime(payload.generated_at),
  };
}

function normalizeSentimentArticle(
  topic: string,
  payload: any,
  partition: number,
  offset: string
): NormalizedNotification {
  const kafkaKey = `${topic}-${partition}-${offset}`;

  return {
    kafkaKey,
    topic,
    category: "news_sentiment",
    title: payload.title || undefined,
    summary: payload.content || undefined,
    sector: payload.stream || undefined,
    sentiment: payload.sentiment || undefined,
    url: payload.url || undefined,
    rawPayload: payload,
    eventTime: parseDateTime(payload.generated_at),
  };
}

function normalizeFilingSignal(
  topic: string,
  payload: any,
  partition: number,
  offset: string
): NormalizedNotification {
  const kafkaKey = `${topic}-${partition}-${offset}`;

  return {
    kafkaKey,
    topic,
    category: "filing_signal",
    title: payload.symbol ? `Filing Signal: ${payload.symbol}` : undefined,
    summary: payload.explanation || undefined,
    symbol: payload.symbol || undefined,
    signal: payload.signal !== undefined ? String(payload.signal) : undefined,
    confidence: typeof payload.confidence === "number" ? payload.confidence : undefined,
    rawPayload: payload,
    eventTime: parseDateTime(payload.filing_time || payload.generated_at),
  };
}

function normalizeSectorAnalysis(
  topic: string,
  payload: any,
  partition: number,
  offset: string
): NormalizedNotification {
  const kafkaKey = `${topic}-${partition}-${offset}`;

  return {
    kafkaKey,
    topic,
    category: "sector_analysis",
    title: "Sector Analysis",
    summary: payload.analysis || undefined,
    sector: payload.sector || undefined,
    rawPayload: payload,
    eventTime: parseDateTime(payload.generated_at),
  };
}

function normalizeEvent(
  topic: string,
  payload: any,
  partition: number,
  offset: string
): NormalizedNotification | null {
  const topicLower = topic.toLowerCase();

  if (topicLower.includes("stock") && topicLower.includes("recomendation")) {
    return normalizeStockRecommendation(topic, payload, partition, offset);
  }

  if (topicLower.includes("sentiment") && topicLower.includes("article")) {
    return normalizeSentimentArticle(topic, payload, partition, offset);
  }

  if (topicLower.includes("nse") && topicLower.includes("filing") && topicLower.includes("signal")) {
    return normalizeFilingSignal(topic, payload, partition, offset);
  }

  if (topicLower.includes("sector") && topicLower.includes("analysis")) {
    return normalizeSectorAnalysis(topic, payload, partition, offset);
  }

  console.warn(`[Kafka] Unknown topic format: ${topic}`);
  return null;
}

export class NotificationConsumer {
  private kafka: Kafka;
  private consumer: Consumer;
  private prisma: PrismaClient;
  private publisher: NotificationPublisher;
  private isRunning: boolean = false;

  constructor(prisma: PrismaClient, publisher: NotificationPublisher) {
    this.kafka = buildKafkaClient();
    this.consumer = this.kafka.consumer({
      groupId: notificationConfig.KAFKA_GROUP_ID || "notifications-consumer",
      allowAutoTopicCreation: false,
      sessionTimeout: 30000,
      heartbeatInterval: 3000,
      maxInFlightRequests: 1,
    });
    this.prisma = prisma;
    this.publisher = publisher;
  }

  private async sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  private async subscribeWithRetry(maxRetries: number = 10, initialDelay: number = 2000): Promise<void> {
    const topics = [
      "news_pipeline_stock_recomendations",
      "news_pipeline_sentiment_articles",
      "nse_filings_trading_signal",
      "news_pipeline_sector_analysis",
    ];

    let delay = initialDelay;
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        await this.consumer.subscribe({
          topics,
          fromBeginning: false,
        });

        console.log(`[Kafka] Successfully subscribed to topics: ${topics.join(", ")}`);
        return;
      } catch (error: any) {
        lastError = error;
        const isTopicError = 
          error?.type === "UNKNOWN_TOPIC_OR_PARTITION" ||
          error?.code === 3 ||
          error?.message?.includes("does not host this topic-partition") ||
          error?.message?.includes("UNKNOWN_TOPIC_OR_PARTITION");

        if (isTopicError && attempt < maxRetries) {
          console.warn(
            `[Kafka] Topics not available yet (attempt ${attempt}/${maxRetries}). Retrying in ${delay}ms...`
          );
          await this.sleep(delay);
          delay = Math.min(delay * 1.5, 30000);
        } else {
          throw error;
        }
      }
    }

    throw lastError || new Error("Failed to subscribe to topics after retries");
  }

  async connect(): Promise<void> {
    try {
      await this.consumer.connect();
      console.log("[Kafka] Consumer connected");

      await this.subscribeWithRetry();

      console.log("[Kafka] Ready to consume messages");
    } catch (error) {
      console.error("[Kafka] Failed to connect:", error);
      throw error;
    }
  }

  private async processMessage(payload: EachMessagePayload): Promise<void> {
    const { topic, partition, message } = payload;
    const offset = message.offset;

    try {
      let rawPayload: any = parseJsonSafely(message.value);
      if (!rawPayload) {
        console.warn(`[Kafka] Failed to parse message value as JSON (topic: ${topic}, partition: ${partition}, offset: ${offset})`);
        return;
      }

      rawPayload = normalizePayload(rawPayload);

      const normalized = normalizeEvent(topic, rawPayload, partition, offset);
      if (!normalized) {
        console.warn(`[Kafka] Could not normalize event from topic: ${topic}`);
        return;
      }

      const notification = await this.prisma.notification.upsert({
        where: { kafkaKey: normalized.kafkaKey },
        update: {},
        create: {
          kafkaKey: normalized.kafkaKey,
          topic: normalized.topic,
          category: normalized.category,
          title: normalized.title,
          summary: normalized.summary,
          symbol: normalized.symbol,
          sector: normalized.sector,
          sentiment: normalized.sentiment,
          signal: normalized.signal,
          confidence: normalized.confidence,
          url: normalized.url,
          rawPayload: normalized.rawPayload,
          eventTime: normalized.eventTime,
        },
      });

      console.log(`[DB] Upserted notification: ${notification.id} (kafkaKey: ${normalized.kafkaKey})`);

      await this.publisher.publish(notification);
    } catch (error) {
      console.error(`[Kafka] Error processing message (topic: ${topic}, partition: ${partition}, offset: ${offset}):`, error);
    }
  }

  async start(): Promise<void> {
    if (this.isRunning) {
      console.warn("[Kafka] Consumer is already running");
      return;
    }

    await this.connect();
    this.isRunning = true;

    await this.consumer.run({
      eachMessage: async (payload) => {
        await this.processMessage(payload);
      },
    });

    console.log("[Kafka] Consumer started and listening for messages");
  }

  async stop(): Promise<void> {
    if (!this.isRunning) {
      return;
    }

    try {
      await this.consumer.stop();
      await this.consumer.disconnect();
      this.isRunning = false;
      console.log("[Kafka] Consumer stopped and disconnected");
    } catch (error) {
      console.error("[Kafka] Error stopping consumer:", error);
    }
  }
}

