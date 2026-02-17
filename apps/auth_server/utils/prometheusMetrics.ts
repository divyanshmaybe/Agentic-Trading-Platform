/**
 * Prometheus HTTP Metrics Middleware for Express
 *
 * Exposes HTTP request metrics for the Auth Server API.
 */

import { Request, Response, NextFunction } from "express";
import client from "prom-client";

// Create a Registry
export const register = new client.Registry();

// Add default metrics (CPU, memory, etc.)
client.collectDefaultMetrics({ register });

// HTTP Request Metrics
export const httpRequestsTotal = new client.Counter({
  name: "http_requests_total",
  help: "Total number of HTTP requests",
  labelNames: ["method", "endpoint", "status_code"],
  registers: [register],
});

export const httpRequestDurationSeconds = new client.Histogram({
  name: "http_request_duration_seconds",
  help: "HTTP request duration in seconds",
  labelNames: ["method", "endpoint"],
  buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
  registers: [register],
});

export const httpRequestsInProgress = new client.Gauge({
  name: "http_requests_in_progress",
  help: "Number of HTTP requests currently being processed",
  labelNames: ["method", "endpoint"],
  registers: [register],
});

export const httpRequestSizeBytes = new client.Histogram({
  name: "http_request_size_bytes",
  help: "HTTP request size in bytes",
  labelNames: ["method", "endpoint"],
  buckets: [100, 1000, 10000, 100000, 1000000, 10000000],
  registers: [register],
});

export const httpResponseSizeBytes = new client.Histogram({
  name: "http_response_size_bytes",
  help: "HTTP response size in bytes",
  labelNames: ["method", "endpoint"],
  buckets: [100, 1000, 10000, 100000, 1000000, 10000000],
  registers: [register],
});

/**
 * Normalize path to reduce cardinality.
 * Replace dynamic path segments (UUIDs, IDs) with placeholders.
 */
function normalizePath(path: string): string {
  // Replace UUIDs
  path = path.replace(
    /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi,
    "{uuid}"
  );

  // Replace numeric IDs (standalone numbers in path)
  path = path.replace(/\/\d+(?=\/|$)/g, "/{id}");

  // Replace timestamps
  path = path.replace(/\/\d{10,13}(?=\/|$)/g, "/{timestamp}");

  return path;
}

/**
 * Prometheus metrics middleware for Express
 */
export function prometheusMiddleware(
  req: Request,
  res: Response,
  next: NextFunction
): void {
  // Skip metrics endpoint to avoid recursion
  if (req.path === "/metrics") {
    return next();
  }

  const method = req.method;
  const path = normalizePath(req.path);
  const startTime = process.hrtime();

  // Track request in progress
  httpRequestsInProgress.labels(method, path).inc();

  // Track request size
  const contentLength = req.headers["content-length"];
  if (contentLength) {
    httpRequestSizeBytes.labels(method, path).observe(parseInt(contentLength, 10));
  }

  // Capture original end function
  const originalEnd = res.end;

  // Override end function to capture metrics
  res.end = function (
    this: Response,
    chunk?: any,
    encoding?: BufferEncoding | (() => void),
    callback?: () => void
  ): Response {
    // Calculate duration
    const diff = process.hrtime(startTime);
    const duration = diff[0] + diff[1] / 1e9;

    // Record metrics
    httpRequestsTotal.labels(method, path, res.statusCode.toString()).inc();
    httpRequestDurationSeconds.labels(method, path).observe(duration);

    // Track response size
    const responseSize = res.getHeader("content-length");
    if (responseSize) {
      httpResponseSizeBytes
        .labels(method, path)
        .observe(parseInt(responseSize.toString(), 10));
    }

    // Decrease in-progress counter
    httpRequestsInProgress.labels(method, path).dec();

    // Call original end
    return originalEnd.call(this, chunk, encoding as BufferEncoding, callback);
  };

  next();
}

/**
 * Metrics endpoint handler
 */
export async function metricsEndpoint(
  req: Request,
  res: Response
): Promise<void> {
  res.set("Content-Type", register.contentType);
  res.end(await register.metrics());
}
