import dotenv from "dotenv";
dotenv.config({ path: "../../.env" });
dotenv.config({ path: ".env" });

export const authConfig = {
  NODE_ENV:
    (process.env.NODE_ENV as "development" | "production" | "test") ||
    "development",
  PORT: Number(process.env.PORT) || 4000,
  DATABASE_URL: process.env.DATABASE_URL || "",
  SESSION_SECRET: process.env.SESSION_SECRET || "",
  CLIENT_URL: process.env.CLIENT_URL || "",
  JWT_SECRET_ACCESS: process.env.JWT_SECRET_ACCESS || "",
  JWT_SECRET_REFRESH: process.env.JWT_SECRET_REFRESH || "",
  JWT_SECRET_EMAIL: process.env.JWT_SECRET_EMAIL || "",
  INTERNAL_SERVICE_SECRET: process.env.INTERNAL_SERVICE_SECRET || "",
  ALLOW_SIGNUP: process.env.ALLOW_SIGNUP === "false" ? false : true,
};

export const allowedOrigins = [
  process.env.CLIENT_URL || "http://localhost:3000",
  process.env.AUTH_SERVER_URL || "http://localhost:4000",
  process.env.PORTFOLIO_SERVICE_URL || "http://localhost:8000",
];
