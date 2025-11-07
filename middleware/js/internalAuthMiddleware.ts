import { Request, Response, NextFunction } from "express";
import dotenv from "dotenv";
import path from "path";

// Load .env from project root
dotenv.config({ path: path.resolve(__dirname, "../../.env") });

export function internalAuth(req: Request, res: Response, next: NextFunction) {
  const serviceSecret = req.headers["x-service-secret"];
  const isInternal = req.headers["x-internal-service"];

  // Debug logging (remove in production)
  console.log("🔐 Internal Auth Check:", {
    receivedSecret: serviceSecret,
    expectedSecret: process.env.INTERNAL_SERVICE_SECRET,
    isInternal,
    match: serviceSecret === process.env.INTERNAL_SERVICE_SECRET
  });

  if (!isInternal || serviceSecret !== process.env.INTERNAL_SERVICE_SECRET) {
    return res.status(403).json({ error: "Internal access only" });
  }
  next();
}
