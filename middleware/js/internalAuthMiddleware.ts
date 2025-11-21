import { Request, Response, NextFunction } from "express";
import crypto from "crypto";
import dotenv from "dotenv";
import path from "path";

// Load .env from project root
dotenv.config({ path: path.resolve(__dirname, "../../.env") });

/**
 * Constant-time string comparison to prevent timing attacks
 */
function timingSafeEqual(a: string, b: string): boolean {
  if (typeof a !== "string" || typeof b !== "string") {
    return false;
  }
  
  const bufferA = Buffer.from(a);
  const bufferB = Buffer.from(b);
  
  // If lengths differ, use dummy buffers to maintain constant time
  if (bufferA.length !== bufferB.length) {
    // Still compare to maintain constant time
    const dummyBuffer = Buffer.alloc(bufferA.length);
    crypto.timingSafeEqual(bufferA, dummyBuffer);
    return false;
  }
  
  return crypto.timingSafeEqual(bufferA, bufferB);
}

export function internalAuth(req: Request, res: Response, next: NextFunction) {
  const serviceSecret = req.headers["x-service-secret"];
  const isInternal = req.headers["x-internal-service"];
  const expectedSecret = process.env.INTERNAL_SERVICE_SECRET;

  // SECURITY: Use timing-safe comparison to prevent timing attacks
  if (
    !isInternal ||
    typeof serviceSecret !== "string" ||
    !expectedSecret ||
    !timingSafeEqual(serviceSecret, expectedSecret)
  ) {
    return res.status(403).json({ error: "Internal access only" });
  }
  next();
}
