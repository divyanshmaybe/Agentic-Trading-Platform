import { Request, Response, NextFunction } from "express";
import { ErrorHandling } from "./errorHandler";
import { authClient } from "../../shared/js/authService.client";

declare global {
  namespace Express {
    interface Request {
      user?: {
        _id: string;
        email: string;
        firstName: string;
        lastName: string;
        role: "admin" | "staff" | "viewer";
        organizationId: string;
        isEmailVerified: boolean;
      };
    }
  }
}

// Protect route middleware
export const protectRoute = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  try {
    // Allow CORS preflight requests to pass through without auth checks
    if (req.method === "OPTIONS") {
      return next();
    }

    let token: string | undefined;

    // Get token from Authorization header
    if (
      req.headers.authorization &&
      req.headers.authorization.startsWith("Bearer ")
    ) {
      token = req.headers.authorization.split(" ")[1];
    } else if (req.cookies && req.cookies.token) {
      token = req.cookies.token;
    }

    if (!token) {
      return next(new ErrorHandling("Not authorized, no token", 401));
    }
    // Validate token
    const validation = await authClient.validateToken(token);

    if (!validation.valid) {
      // Return specific error message from validation
      const errorMsg = validation.error || "Invalid token";
      return next(new ErrorHandling(errorMsg, 401));
    }

    if (!validation.user) {
      return next(new ErrorHandling("Invalid token", 401));
    }

    // Attach user to request
    req.user = validation.user;
    next();
  } catch (err: any) {
    console.error("❌ Auth middleware error:", err);
    return next(new ErrorHandling("Not authorized, invalid token", 401));
  }
};

// Role-based middleware functions
// These should be used AFTER protectRoute middleware

/**
 * Middleware to check if user is an admin
 * Usage: router.get("/admin-only", protectRoute, isAdmin, handler);
 */
export const isAdmin = (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  if (!req.user) {
    return next(new ErrorHandling("Not authenticated", 401));
  }

  if (req.user.role !== "admin") {
    return next(
      new ErrorHandling("Access denied. Admin privileges required.", 403)
    );
  }

  next();
};

/**
 * Middleware to check if user is staff (staff or admin)
 * Usage: router.get("/staff-only", protectRoute, isStaff, handler);
 */
export const isStaff = (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  if (!req.user) {
    return next(new ErrorHandling("Not authenticated", 401));
  }

  if (req.user.role !== "staff" && req.user.role !== "admin") {
    return next(
      new ErrorHandling("Access denied. Staff privileges required.", 403)
    );
  }

  next();
};

/**
 * Middleware to check if user is authenticated (any role)
 * This is essentially the same as protectRoute but can be used for clarity
 * Usage: router.get("/user-only", protectRoute, isUser, handler);
 */
export const isUser = (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  if (!req.user) {
    return next(new ErrorHandling("Not authenticated", 401));
  }

  // Any authenticated user can proceed
  next();
};
