import { readFileSync } from "node:fs";
import { Kafka, logLevel, Consumer, EachMessagePayload, SASLOptions } from "kafkajs";
import { PrismaClient } from "@prisma/client";
import { notificationConfig } from "../../config";
import { NotificationPublisher, LowRiskPublisher } from "../redis/publisher";
import {
	recordMessageProcessed,
	recordDelivery,
	recordError,
	recordLowRiskEvent,
} from "../metrics";
import {
	isLowRiskEvent,
	isLowRiskInfoEvent,
	isLowRiskIndustryEventFetching,
	isLowRiskIndustryEventFetched,
	isLowRiskIndustryEventDone,
	isLowRiskStockEventFetching,
	isLowRiskStockEventFetched,
	isLowRiskReportEventCached,
	isLowRiskReportEventGenerating,
	isLowRiskReportEventGenerated,
	isLowRiskReasoningEvent,
	isLowRiskSummaryEvent,
	isLowRiskStageEvent,
	isLowRiskMetricsEvent,
	isLowRiskValueEnvelope,
} from "./validators";
import { LowRiskNormalized, LowRiskEvent, LowRiskValueEnvelope } from "./types/lowRisk";

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

/**
 * Robustly unwrap nested value strings from Kafka messages
 * Handles cases like: {"value": {"value": "{\"user_id\":\"...\"}"}}
 * 
 * @param raw - The raw Kafka message value (string, Buffer, or object)
 * @returns The unwrapped object or null if unwrapping fails or result is not an object
 */
function unwrapNestedValue(raw: string | Buffer | object | null | undefined): any {
	const MAX_ITERATIONS = 5;

	// Convert Buffer to string
	let current: any = raw;
	if (Buffer.isBuffer(current)) {
		try {
			current = current.toString("utf8");
		} catch {
			return null;
		}
	}

	// If already an object (not string), return it if it's a valid object
	if (current !== null && typeof current === "object" && !Array.isArray(current)) {
		return current;
	}

	// If not a string, return null (we only accept objects)
	if (typeof current !== "string") {
		return null;
	}

	let lastValid: any = null;
	let iterations = 0;

	while (iterations < MAX_ITERATIONS && typeof current === "string") {
		iterations++;

		try {
			const parsed = JSON.parse(current);

			// If parsed value is not an object/array, return null (we only accept objects)
			if (parsed === null || (typeof parsed !== "object")) {
				return null;
			}

			// If it's an array, return null (we only accept objects)
			if (Array.isArray(parsed)) {
				return null;
			}

			lastValid = parsed;

			// Check if parsed object has a "value" field that is a string - continue unwrapping
			if ("value" in parsed && typeof parsed.value === "string") {
				current = parsed.value;
			} else {
				// No more nested value, return the parsed object
				return parsed;
			}
		} catch {
			// Parse failed - return last valid object or null
			return lastValid;
		}
	}

	// Max iterations reached - return last valid object or null
	return lastValid;
}

/**
 * Normalize payload - kept for backward compatibility with existing normalizers
 * For low-risk events, use unwrapNestedValue directly instead
 */
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

/**
 * Strict datetime parser with validation
 * Handles multiple timestamp field sources and validates inputs
 */
function parseDateTimeStrict(value: string | number | Date | undefined | null): Date | undefined {
	if (!value) return undefined;

	// Already a Date
	if (value instanceof Date) {
		if (!isNaN(value.getTime())) {
			return value;
		}
		return undefined;
	}

	// Number: treat as ms since epoch
	if (typeof value === "number") {
		// Validate reasonable range: between year 2000 and year 2100
		const MIN_TS = 946684800000; // 2000-01-01
		const MAX_TS = 4102444800000; // 2100-01-01

		if (value >= MIN_TS && value <= MAX_TS) {
			const date = new Date(value);
			if (!isNaN(date.getTime())) {
				return date;
			}
		}
		return undefined;
	}

	// String: validate length and parse
	if (typeof value === "string") {
		// Reject strings that are too short (likely not timestamps)
		if (value.length < 8) {
			return undefined;
		}

		const parsed = new Date(value);
		if (!isNaN(parsed.getTime())) {
			return parsed;
		}
	}

	return undefined;
}

/**
 * Legacy datetime parser - kept for backward compatibility
 */
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

	// Handle nested value.value structure (similar to low-risk events)
	// The payload might be wrapped in {key, value} where value is a JSON string
	// normalizePayload may have already unwrapped it, but we handle both cases
	let unwrappedPayload: any = payload;

	// First, try unwrapNestedValue to handle deeply nested structures
	const unwrapped = unwrapNestedValue(payload);
	if (unwrapped) {
		unwrappedPayload = unwrapped;
	}

	// If unwrappedPayload still has a "value" field that's a string, parse it
	// This handles the case where normalizePayload didn't fully unwrap it
	if (unwrappedPayload && typeof unwrappedPayload === "object" && !Array.isArray(unwrappedPayload)) {
		if ("value" in unwrappedPayload && typeof unwrappedPayload.value === "string") {
			try {
				const parsed = JSON.parse(unwrappedPayload.value);
				if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
					unwrappedPayload = parsed;
				}
			} catch {
				// If parsing fails, continue with unwrappedPayload as-is
			}
		}
	}

	// Extract fields from the unwrapped payload
	const symbol = unwrappedPayload?.symbol || undefined;
	const explanation = unwrappedPayload?.explanation || undefined;
	const signal = unwrappedPayload?.signal !== undefined ? String(unwrappedPayload.signal) : undefined;
	const confidence = typeof unwrappedPayload?.confidence === "number" ? unwrappedPayload.confidence : undefined;
	const attachmentUrl = unwrappedPayload?.attachment_url || undefined;
	const subjectOfAnnouncement = unwrappedPayload?.subject_of_announcement || undefined;
	const dateTimeOfSubmission = unwrappedPayload?.date_time_of_submission || undefined;
	const filingTime = unwrappedPayload?.filing_time || undefined;
	const generatedAt = unwrappedPayload?.generated_at || undefined;

	// Use attachment_url for url field if available
	const url = attachmentUrl || unwrappedPayload?.url || undefined;

	// Parse eventTime from filing_time, date_time_of_submission, or generated_at (in that order)
	const eventTime = parseDateTimeStrict(filingTime) ||
		parseDateTimeStrict(dateTimeOfSubmission) ||
		parseDateTimeStrict(generatedAt) ||
		undefined;

	return {
		kafkaKey,
		topic,
		category: "filing_signal",
		title: symbol ? `Filing Signal: ${symbol}` : undefined,
		summary: explanation || undefined,
		symbol,
		signal,
		confidence,
		url,
		rawPayload: unwrappedPayload, // Preserve all fields including subject_of_announcement, attachment_url, date_time_of_submission
		eventTime,
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

/**
 * Parse and normalize a low-risk event from Kafka message
 * Handles new envelope structure with strict union types
 * 
 * @param payload - EachMessagePayload from kafkajs
 * @returns LowRiskNormalized | null (null if parsing fails or userId missing)
 */
function parseLowRiskKafkaMessage(payload: EachMessagePayload): LowRiskNormalized | null {
	const { topic, partition, message } = payload;
	const offset = message.offset;

	// Extract Kafka timestamp - ALWAYS use this, never payload timestamps
	const kafkaTimestamp = message.timestamp ? Number(message.timestamp) : NaN;
	let eventTime: Date;

	if (!isNaN(kafkaTimestamp) && kafkaTimestamp > 0) {
		eventTime = new Date(kafkaTimestamp);
	} else {
		// Invalid or missing Kafka timestamp - fallback to now() with warning
		eventTime = new Date();
		console.warn(`[Kafka][LowRisk] Warning: invalid Kafka timestamp; using now() (topic=${topic}, partition=${partition}, offset=${offset})`);
	}

	// Parse message.value as LowRiskValueEnvelope
	let valueEnvelope: LowRiskValueEnvelope;
	try {
		const rawValue = parseJsonSafely(message.value);
		if (!rawValue || typeof rawValue !== "object") {
			console.warn(`[Kafka][LowRisk] Dropped: message.value is not an object (topic=${topic}, partition=${partition}, offset=${offset})`);
			return null;
		}

		// Check if it's already a LowRiskValueEnvelope or needs unwrapping
		if (isLowRiskValueEnvelope(rawValue)) {
			valueEnvelope = rawValue;
		} else {
			// Try to unwrap nested structure
			const unwrapped = unwrapNestedValue(message.value);
			if (unwrapped && isLowRiskValueEnvelope(unwrapped)) {
				valueEnvelope = unwrapped;
			} else {
				console.warn(`[Kafka][LowRisk] Dropped: message.value is not a LowRiskValueEnvelope (topic=${topic}, partition=${partition}, offset=${offset})`);
				return null;
			}
		}
	} catch (error) {
		console.warn(`[Kafka][LowRisk] Dropped: failed to parse message.value (topic=${topic}, partition=${partition}, offset=${offset}):`, error);
		return null;
	}

	// Parse inner payload JSON from value.value string
	let innerPayload: any;
	try {
		innerPayload = JSON.parse(valueEnvelope.value);
		if (!innerPayload || typeof innerPayload !== "object" || Array.isArray(innerPayload)) {
			console.warn(`[Kafka][LowRisk] Dropped: inner payload is not an object (topic=${topic}, partition=${partition}, offset=${offset})`);
			return null;
		}
	} catch (error) {
		console.warn(`[Kafka][LowRisk] Dropped: failed to parse inner payload JSON (topic=${topic}, partition=${partition}, offset=${offset}):`, error);
		return null;
	}

	// Extract userId: message.key || valueEnvelope.key || innerPayload.user_id
	// Fail ONLY if all three are missing
	const userId = (innerPayload.user_id) as string | undefined;
	if (!userId || typeof userId !== "string" || userId.trim() === "") {
		console.warn(`[Kafka][LowRisk] Dropped: userId missing (topic=${topic}, partition=${partition}, offset=${offset})`);
		return null;
	}

	// Normalize inner payload: convert user_id -> userId, type -> kind
	const normalizedPayload: any = {
		...innerPayload,
		userId,
		kind: innerPayload.type || innerPayload.kind || innerPayload.message_type,
	};

	// Remove old field names and timestamp fields (we use Kafka timestamp only)
	delete normalizedPayload.user_id;
	delete normalizedPayload.type;
	delete normalizedPayload.timestamp;
	delete normalizedPayload.time;

	// Validate against strict union types
	if (!isLowRiskEvent(normalizedPayload)) {
		console.warn(`[Kafka][LowRisk] Dropped: unknown event type (topic=${topic}, partition=${partition}, offset=${offset}, kind=${normalizedPayload.kind})`);
		return null;
	}

	const event: LowRiskEvent = normalizedPayload;

	// Map event to LowRiskNormalized format
	let eventType: string | null = null;
	let status: string | null = null;
	let content: any | null = null;

	if (isLowRiskInfoEvent(event)) {
		eventType = null;
		status = null;
		content = { message: event.content };
	} else if (isLowRiskIndustryEventFetching(event)) {
		eventType = "industry";
		status = "fetching";
		content = event.content;
	} else if (isLowRiskIndustryEventFetched(event)) {
		eventType = "industry";
		status = "fetched";
		content = event.content;
	} else if (isLowRiskIndustryEventDone(event)) {
		eventType = "industry";
		status = "done";
		content = event.content;
	} else if (isLowRiskStockEventFetching(event)) {
		eventType = "stock";
		status = "fetching";
		content = event.content;
	} else if (isLowRiskStockEventFetched(event)) {
		eventType = "stock";
		status = "fetched";
		content = event.content;
	} else if (isLowRiskReportEventCached(event)) {
		eventType = "report";
		status = "cached";
		content = event.content;
	} else if (isLowRiskReportEventGenerating(event)) {
		eventType = "report";
		status = "generating";
		content = event.content;
	} else if (isLowRiskReportEventGenerated(event)) {
		eventType = "report";
		status = "generated";
		content = event.content;
	} else if (isLowRiskReasoningEvent(event)) {
		eventType = null;
		status = "thinking";
		content = event.content;
	} else if (isLowRiskSummaryEvent(event)) {
		eventType = null;
		status = null;
		content = event.content;
	} else if (isLowRiskStageEvent(event)) {
		eventType = null;
		status = event.status;
		const result = (normalizedPayload as any).result;
		content = {
			message: event.content,
			stage: event.stage,
			...(result && { result }),
		};
	} else if (isLowRiskMetricsEvent(event)) {
		eventType = null;
		status = null;
		content = event.content;
	}

	return {
		userId,
		kind: event.kind,
		eventType,
		status,
		content,
		rawPayload: innerPayload, // Store inner payload, not envelope
		eventTime, // Always from Kafka message timestamp
		topic,
		partition,
		offset,
	};
}

function normalizeEvent(
	topic: string,
	payload: any,
	partition: number,
	offset: string
): NormalizedNotification | null {
	const topicLower = topic.toLowerCase();

	// Handle low-risk events separately (they return ParsedLowRiskEvent, not NormalizedNotification)
	if (topicLower.includes("low_risk") || topicLower === "low_risk_agent_logs") {
		// Low-risk events are handled in processMessage directly, not through normalizeEvent
		return null;
	}

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
	private lowRiskPublisher: LowRiskPublisher;
	private isRunning: boolean = false;

	constructor(prisma: PrismaClient, publisher: NotificationPublisher, lowRiskPublisher: LowRiskPublisher) {
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
		this.lowRiskPublisher = lowRiskPublisher;
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
			"low_risk_agent_logs",
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
		const startTime = Date.now();

		try {
			// Handle low-risk events separately with strict validation
			if (topic === "low_risk_agent_logs" || topic.toLowerCase().includes("low_risk")) {
				// Parse using new envelope structure and strict union types
				const normalized = parseLowRiskKafkaMessage(payload);

				if (!normalized) {
					// Parser already logged the reason for dropping
					recordMessageProcessed(topic, "skipped");
					return;
				}

				// Strict user validation - check if user exists in DB
				const user = await this.prisma.user.findUnique({
					where: { id: normalized.userId },
				});

				if (!user) {
					console.warn(`[Kafka][LowRisk] Dropped event — user not found (userId=${normalized.userId}, topic=${topic}, partition=${partition}, offset=${offset})`);
					console.warn(`[Kafka][LowRisk] lowrisk_dropped_user_not_found`);
					recordMessageProcessed(topic, "skipped");
					return; // STOP PROCESSING - DO NOT WRITE TO DB, DO NOT PUBLISH
				}

				// User exists - create DB record with typed fields

				// SPECIAL HANDLING FOR METRICS: Store in LowRiskUserSummaries and STOP (no Redis, no LowRiskEvent)
				if (normalized.kind === "metrics") {
					try {
						// Delete old metrics for this user
						await this.prisma.lowRiskUserSummaries.deleteMany({
							where: {
								userId: normalized.userId,
								type: "metrics",
							},
						});

						await this.prisma.lowRiskUserSummaries.create({
							data: {
								userId: normalized.userId,
								type: "metrics",
								jsonContent: normalized.content,
							},
						});
						console.log(`[DB][LowRisk] Created metrics record for user ${normalized.userId}`);
						recordDelivery("postgres", "success");
						recordLowRiskEvent("metrics", "processed");
						recordMessageProcessed(topic, "processed", Date.now() - startTime);
					} catch (err) {
						console.error(`[DB][LowRisk] Failed to create metrics record for user ${normalized.userId}:`, err);
						recordDelivery("postgres", "failed");
						recordError(topic, "db_error");
						recordMessageProcessed(topic, "failed", Date.now() - startTime);
					}
					return;
				}

				// eventTime comes ONLY from Kafka message timestamp (normalized.eventTime is always set)
				const event = await this.prisma.lowRiskEvent.create({
					data: {
						userId: normalized.userId,
						kind: normalized.kind,
						eventType: normalized.eventType ?? null,
						status: normalized.status ?? null,
						content: normalized.content ?? null,
						rawPayload: normalized.rawPayload,
						eventTime: normalized.eventTime, // Always from Kafka timestamp
					},
				});

				console.log(`[DB][LowRisk] Created event ${event.id} for user ${normalized.userId} kind=${normalized.kind} with eventTime=${normalized.eventTime.toISOString()}`);
				console.warn(`[Kafka][LowRisk] lowrisk_processed_success`);
				recordDelivery("postgres", "success");
				recordLowRiskEvent(normalized.kind, "processed");

				// If this is a summary event, also write to LowRiskUserSummaries table
				if (normalized.kind === "summary" && normalized.content) {
					try {
						// Delete old summary for this user
						await this.prisma.lowRiskUserSummaries.deleteMany({
							where: {
								userId: normalized.userId,
								type: "summary",
							},
						});

						const summaryRecord = await this.prisma.lowRiskUserSummaries.create({
							data: {
								userId: normalized.userId,
								type: "summary",
								jsonContent: normalized.content,
							},
						});
						console.log(`[DB][LowRisk] Created summary record ${summaryRecord.id} for user ${normalized.userId}`);
					} catch (summaryError) {
						console.error(`[DB][LowRisk] Failed to create summary record for user ${normalized.userId}:`, summaryError);
						// Don't throw - we still want to publish the event even if summary write fails
					}
				}

				// Publish to Redis per-user channel (sequential, after DB write)
				// normalized.eventTime is already set from Kafka timestamp
				try {
					await this.lowRiskPublisher.publish({
						...normalized,
						id: event.id,
						createdAt: event.createdAt,
					});
					recordDelivery("redis", "success");
				} catch (redisError) {
					// Redis failures don't block Kafka processing - log and continue
					console.error(`[Redis][LowRisk] Failed to publish event ${event.id}:`, redisError);
					recordDelivery("redis", "failed");
					recordError(topic, "redis_error");
				}

				recordMessageProcessed(topic, "processed", Date.now() - startTime);
				return;
			}

			// Handle regular notification events (unchanged)
			let rawPayload: any = parseJsonSafely(message.value);
			if (!rawPayload) {
				console.warn(`[Kafka] Failed to parse message value as JSON (topic: ${topic}, partition: ${partition}, offset: ${offset})`);
				recordMessageProcessed(topic, "failed");
				recordError(topic, "parse_error");
				return;
			}

			rawPayload = normalizePayload(rawPayload);

			const normalized = normalizeEvent(topic, rawPayload, partition, offset);
			if (!normalized) {
				console.warn(`[Kafka] Could not normalize event from topic: ${topic}`);
				recordMessageProcessed(topic, "skipped");
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
			recordDelivery("postgres", "success");

			await this.publisher.publish(notification);
			recordDelivery("redis", "success");
			recordMessageProcessed(topic, "processed", Date.now() - startTime);
		} catch (error) {
			console.error(`[Kafka] Error processing message (topic: ${topic}, partition: ${partition}, offset: ${offset}):`, error);
			recordMessageProcessed(topic, "failed", Date.now() - startTime);
			recordError(topic, "unknown");
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

