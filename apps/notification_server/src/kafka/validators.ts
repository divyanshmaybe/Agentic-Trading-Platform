/**
 * Runtime validators for low-risk event payloads
 * 
 * Type guards for strict union type checking
 */

import {
	LowRiskEvent,
	LowRiskInfoEvent,
	LowRiskIndustryEventFetching,
	LowRiskIndustryEventFetched,
	LowRiskIndustryEventDone,
	LowRiskStockEventFetching,
	LowRiskStockEventFetched,
	LowRiskReportEventCached,
	LowRiskReportEventGenerating,
	LowRiskReportEventGenerated,
	LowRiskReasoningEvent,
	LowRiskSummaryEvent,
	LowRiskStageEvent,
	LowRiskMetricsEvent,
	LowRiskValueEnvelope,
} from "./types/lowRisk";

/**
 * Check if value is a non-null object
 */
export function isObject(v: any): v is Record<string, any> {
	return v !== null && typeof v === "object" && !Array.isArray(v);
}

/**
 * Check if object has a field that is a string
 */
export function hasStringField(obj: any, field: string): boolean {
	return obj !== null && typeof obj === "object" && field in obj && typeof obj[field] === "string";
}

/**
 * Check if value is a LowRiskValueEnvelope
 */
export function isLowRiskValueEnvelope(obj: any): obj is LowRiskValueEnvelope {
	if (!isObject(obj)) {
		return false;
	}

	// Must have key as string
	if (!hasStringField(obj, "key")) {
		return false;
	}

	// Must have value as string (JSON string)
	if (!hasStringField(obj, "value")) {
		return false;
	}

	// Must have headers as object
	if (!("headers" in obj) || typeof obj.headers !== "object" || obj.headers === null || Array.isArray(obj.headers)) {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskInfoEvent
 */
export function isLowRiskInfoEvent(obj: any): obj is LowRiskInfoEvent {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "info") {
		return false;
	}

	if (typeof obj.content !== "string") {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskIndustryEventFetching
 */
export function isLowRiskIndustryEventFetching(obj: any): obj is LowRiskIndustryEventFetching {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "industry") {
		return false;
	}

	if (obj.status !== "fetching") {
		return false;
	}

	if (!isObject(obj.content) || !Array.isArray(obj.content.industries)) {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskIndustryEventFetched
 */
export function isLowRiskIndustryEventFetched(obj: any): obj is LowRiskIndustryEventFetched {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "industry") {
		return false;
	}

	if (obj.status !== "fetched") {
		return false;
	}

	if (!isObject(obj.content)) {
		return false;
	}

	if (!Array.isArray(obj.content.industries)) {
		return false;
	}

	if (!isObject(obj.content.metrics)) {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskIndustryEventDone
 */
export function isLowRiskIndustryEventDone(obj: any): obj is LowRiskIndustryEventDone {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "industry") {
		return false;
	}

	if (obj.status !== "done") {
		return false;
	}

	if (!isObject(obj.content)) {
		return false;
	}

	if (!Array.isArray(obj.content.industries)) {
		return false;
	}

	if (!hasStringField(obj.content, "message")) {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskStockEventFetching
 */
export function isLowRiskStockEventFetching(obj: any): obj is LowRiskStockEventFetching {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "stock") {
		return false;
	}

	if (obj.status !== "fetching") {
		return false;
	}

	if (!isObject(obj.content) || typeof obj.content.content !== "string") {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskStockEventFetched
 */
export function isLowRiskStockEventFetched(obj: any): obj is LowRiskStockEventFetched {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "stock") {
		return false;
	}

	if (obj.status !== "fetched") {
		return false;
	}

	if (!isObject(obj.content) || typeof obj.content.content !== "string") {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskReportEventCached
 */
export function isLowRiskReportEventCached(obj: any): obj is LowRiskReportEventCached {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "report") {
		return false;
	}

	if (obj.status !== "cached") {
		return false;
	}

	if (!isObject(obj.content) || typeof obj.content.ticker !== "string") {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskReportEventGenerating
 */
export function isLowRiskReportEventGenerating(obj: any): obj is LowRiskReportEventGenerating {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "report") {
		return false;
	}

	if (obj.status !== "generating") {
		return false;
	}

	if (!isObject(obj.content) || typeof obj.content.ticker !== "string") {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskReportEventGenerated
 */
export function isLowRiskReportEventGenerated(obj: any): obj is LowRiskReportEventGenerated {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "report") {
		return false;
	}

	if (obj.status !== "generated") {
		return false;
	}

	if (!isObject(obj.content) || typeof obj.content.ticker !== "string") {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskReasoningEvent
 */
export function isLowRiskReasoningEvent(obj: any): obj is LowRiskReasoningEvent {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "reasoning") {
		return false;
	}

	if (obj.status !== "thinking") {
		return false;
	}

	if (!isObject(obj.content) || typeof obj.content.message !== "string") {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskSummaryEvent
 */
export function isLowRiskSummaryEvent(obj: any): obj is LowRiskSummaryEvent {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "summary") {
		return false;
	}

	if (!isObject(obj.content)) {
		return false;
	}

	// Check for required summary fields
	if (!Array.isArray(obj.content.industry_list)) {
		return false;
	}

	if (!Array.isArray(obj.content.final_portfolio)) {
		return false;
	}

	if (!Array.isArray(obj.content.trade_list)) {
		return false;
	}

	if (!isObject(obj.content.summary)) {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskStageEvent
 */
export function isLowRiskStageEvent(obj: any): obj is LowRiskStageEvent {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "stage") {
		return false;
	}

	if (typeof obj.status !== "string") {
		return false;
	}

	if (typeof obj.content !== "string") {
		return false;
	}

	if (typeof obj.stage !== "string") {
		return false;
	}

	return true;
}

/**
 * Type guard for LowRiskMetricsEvent
 */
export function isLowRiskMetricsEvent(obj: any): obj is LowRiskMetricsEvent {
	if (!isObject(obj)) {
		return false;
	}

	if (!hasStringField(obj, "userId")) {
		return false;
	}

	if (obj.kind !== "metrics") {
		return false;
	}

	if (!("content" in obj)) {
		return false;
	}

	return true;
}

/**
 * Type guard for any LowRiskEvent (union type)
 */
export function isLowRiskEvent(obj: any): obj is LowRiskEvent {
	return (
		isLowRiskInfoEvent(obj) ||
		isLowRiskIndustryEventFetching(obj) ||
		isLowRiskIndustryEventFetched(obj) ||
		isLowRiskIndustryEventDone(obj) ||
		isLowRiskStockEventFetching(obj) ||
		isLowRiskStockEventFetched(obj) ||
		isLowRiskReportEventCached(obj) ||
		isLowRiskReportEventGenerating(obj) ||
		isLowRiskReportEventGenerated(obj) ||
		isLowRiskReasoningEvent(obj) ||
		isLowRiskSummaryEvent(obj) ||
		isLowRiskStageEvent(obj) ||
		isLowRiskMetricsEvent(obj)
	);
}
