/**
 * Type definitions for low-risk pipeline events
 * 
 * New Kafka message format:
 * - Root message: { topic, partition, offset, key (userId), timestamp, value (LowRiskValueEnvelope), headers }
 * - Value envelope: { key (userId), value (JSON string), headers, diff, time (IGNORED) }
 * - Inner payload: JSON parsed from value.value string
 */
import { EachMessagePayload } from "kafkajs";

/**
 * Low-risk value envelope from Kafka message.value
 * Contains the nested structure with the actual payload as a JSON string
 */
export interface LowRiskValueEnvelope {
	key: string;                // userId
	value: string;              // JSON string of actual payload
	headers: Record<string, string>;
	diff: number;
	time: number;               // IGNORE this; DO NOT use as timestamp
}

/**
 * Root Kafka message structure for low-risk events
 */
export interface LowRiskKafkaMessage {
	topic: string;
	partition: number;
	offset: number;
	userId: string;             // derived as (message.key || message.value.key)
	timestamp: number;          // ALWAYS use Kafka timestamp, never inner payload timestamp
	value: LowRiskValueEnvelope;
}

/**
 * INFO event - Simple informational messages
 */
export interface LowRiskInfoEvent {
	userId: string;
	kind: "info";
	content: string;            // e.g. "✓ PMI value: 57.4"
}

/**
 * INDUSTRY - FETCHING event
 */
export interface LowRiskIndustryEventFetching {
	userId: string;
	kind: "industry";
	status: "fetching";
	content: {
		industries: string[];
	};
}

/**
 * INDUSTRY - FETCHED event
 */
export interface LowRiskIndustryEventFetched {
	userId: string;
	kind: "industry";
	status: "fetched";
	content: {
		industries: string[];
		metrics: Record<
			string,
			{
				pct_above_ema50: number | null;
				pct_above_ema200: number | null;
				median_rsi: number | null;
				pct_rsi_overbought: number | null;
				pct_rsi_oversold: number | null;
				industry_ret_6m: number | null;
				benchmark_ret_6m: number | null;
			}
		>;
	};
}

/**
 * INDUSTRY - DONE event
 */
export interface LowRiskIndustryEventDone {
	userId: string;
	kind: "industry";
	status: "done";
	content: {
		industries: Array<{
			name: string;
			percentage: number;
			reasoning: string;
		}>;
		message: string;
	};
}

/**
 * STOCK - FETCHING event
 */
export interface LowRiskStockEventFetching {
	userId: string;
	kind: "stock";
	status: "fetching";
	content: {
		content: string;          // ticker symbol
	};
}

/**
 * STOCK - FETCHED event
 */
export interface LowRiskStockEventFetched {
	userId: string;
	kind: "stock";
	status: "fetched";
	content: {
		content: string;          // ticker symbol
	};
}

/**
 * REPORT - GENERATING event
 */
export interface LowRiskReportEventGenerating {
	userId: string;
	kind: "report";
	status: "generating";
	content: {
		ticker: string;
	};
}

/**
 * REPORT - CACHED event
 */
export interface LowRiskReportEventCached {
	userId: string;
	kind: "report";
	status: "cached";
	content: {
		ticker: string;
	};
}

/**
 * REPORT - GENERATED event
 */
export interface LowRiskReportEventGenerated {
	userId: string;
	kind: "report";
	status: "generated";
	content: {
		ticker: string;
	};
}

/**
 * REASONING event - AI reasoning/thinking messages
 */
export interface LowRiskReasoningEvent {
	userId: string;
	kind: "reasoning";
	status: "thinking";
	content: {
		message: string;
	};
}

/**
 * SUMMARY event
 */
export interface LowRiskSummaryEvent {
	userId: string;
	kind: "summary";
	content: {
		industry_list: Array<{
			name: string;
			percentage: number;
			reasoning: string;
		}>;
		final_portfolio: Array<{
			ticker: string;
			percentage: number;
			reasoning: string;
		}>;
		trade_list: Array<{
			ticker: string;
			amount_invested: number;
			no_of_shares_bought: number;
			price_bought: number;
			reasoning: string;
			percentage: number;
		}>;
		summary: {
			total_stocks: number;
			total_trades: number;
			total_invested: number;
			total_shares: number;
			fund_allocated: number;
			utilization_rate: number;
		};
	};
}

/**
 * STAGE event - Pipeline stage progress messages
 */
export interface LowRiskStageEvent {
	userId: string;
	kind: "stage";
	status: string;
	content: string;
	stage: string;
}

/**
 * METRICS event
 */
export interface LowRiskMetricsEvent {
	userId: string;
	kind: "metrics";
	content: any;
}

/**
 * Strict union type for all low-risk events
 */
export type LowRiskEvent =
	| LowRiskInfoEvent
	| LowRiskIndustryEventFetching
	| LowRiskIndustryEventFetched
	| LowRiskIndustryEventDone
	| LowRiskStockEventFetching
	| LowRiskStockEventFetched
	| LowRiskReportEventCached
	| LowRiskReportEventGenerating
	| LowRiskReportEventGenerated
	| LowRiskReasoningEvent
	| LowRiskSummaryEvent
	| LowRiskStageEvent
	| LowRiskMetricsEvent;

/**
 * Normalized low-risk event (server-side representation)
 * eventTime is ALWAYS derived from Kafka message timestamp, never from payload
 * Maps to Prisma LowRiskEvent model
 */
export type LowRiskNormalized = {
	userId: string;
	kind: "info" | "industry" | "stock" | "report" | "reasoning" | "summary" | "stage" | "metrics";
	eventType: string | null;   // null for info/reasoning/summary/stage, "industry"/"stock"/"report" for others
	status: string | null;      // "fetching" | "fetched" | "done" | "cached" | "generating" | "generated" | "thinking" | "start" | "progress" | "done" | "error" | null
	content: any | null;
	rawPayload: any;            // full inner payload JSON
	eventTime: Date;            // Required - strictly from Kafka message timestamp
	topic: string;
	partition: number;
	offset: string;
};
