/**
 * Runtime validators for low-risk event payloads
 * 
 * TODO: If we later want stronger schemas, replace these guards with Zod or io-ts validators.
 */

import { LowRiskLogPayload, LowRiskNotificationPayload } from "./types/lowRisk";

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
 * Strict validator for low-risk notification payloads
 * Returns true only if all required fields are present and correctly typed
 */
export function isLowRiskNotification(obj: any): obj is LowRiskNotificationPayload {
  if (!isObject(obj)) {
    return false;
  }

  // Must have user_id as string
  if (!hasStringField(obj, "user_id")) {
    return false;
  }

  // Must have type as string
  if (!hasStringField(obj, "type")) {
    return false;
  }

  // Must have content as object
  if (!("content" in obj) || typeof obj.content !== "object" || obj.content === null || Array.isArray(obj.content)) {
    return false;
  }

  return true;
}

/**
 * Strict validator for low-risk log payloads
 * Returns true only if user_id is present and at least one log-related field exists
 */
export function isLowRiskLog(obj: any): obj is LowRiskLogPayload {
  if (!isObject(obj)) {
    return false;
  }

  // Must have user_id as string
  if (!hasStringField(obj, "user_id")) {
    return false;
  }

  // Must have at least one log-related field (message, level, or stage)
  // This distinguishes logs from notifications
  const hasLogField = "message" in obj || "level" in obj || "stage" in obj;
  if (!hasLogField) {
    return false;
  }

  // Should NOT have both type and content (that would be a notification)
  if ("type" in obj && "content" in obj) {
    return false;
  }

  return true;
}
