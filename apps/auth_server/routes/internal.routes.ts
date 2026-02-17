import { Router } from "express";
import jwt from "jsonwebtoken";
import { prisma } from "../lib/prisma";
import { internalAuth } from "../../../middleware/js/internalAuthMiddleware";
import { setUserFromApiEmail } from "../../../middleware/js/setUserFromApiEmail";
import { generateUsername } from "../utils/username";

const router: Router = Router();

router.use(internalAuth);
router.use(setUserFromApiEmail);

router.post("/validate-token", async (req, res) => {
  try {
    const { token } = req.body;

    if (!token) {
      return res.status(400).json({ error: "Token is required" });
    }

    const decoded = jwt.verify(token, process.env.JWT_SECRET_ACCESS!) as any;
    const user = await prisma.user.findFirst({
      where: { 
        id: decoded.id,
        deleted_at: null,
      },
      select: {
        id: true,
        email: true,
        first_name: true,
        last_name: true,
        role: true,
        organization_id: true,
        status: true,
        organization: {
          select: {
            name: true,
          },
        },
      },
    });

    if (!user) {
      return res.status(401).json({ error: "User not found" });
    }

    if (user.status !== "active") {
      return res.status(401).json({ error: "User account is not active" });
    }

    // Generate username from user data (computed, not stored)
    // This is the ONLY source of truth for username - cannot be manipulated by client
    const username = generateUsername(
      user.first_name,
      user.last_name,
      user.organization.name
    );

    res.json({
      valid: true,
      user: {
        _id: user.id,
        email: user.email,
        firstName: user.first_name,
        lastName: user.last_name,
        role: user.role,
        organizationId: user.organization_id,
        isEmailVerified: user.status === "active",
        username: username, // Server-computed, secure username
      },
    });
  } catch (error: any) {
    res.status(401).json({
      valid: false,
      error:
        error.name === "TokenExpiredError" ? "Token expired" : "Invalid token",
    });
  }
});

router.get("/get-user-email/:userId", async (req, res) => {
  try {
    const { userId } = req.params;
    const user = await prisma.user.findUnique({
      where: { id: userId },
      select: { email: true },
    });

    if (!user) {
      return res.status(404).json({ error: "User not found" });
    }

    res.json({ email: user.email });
  } catch (error) {
    res.status(500).json({ error: "Internal server error" });
  }
});

router.get("/get-user-details/:userId", async (req, res) => {
  try {
    const { userId } = req.params;
    
    // SECURITY: Optional organization boundary check
    // If requesting service provides organization_id, validate it matches
    const requestedOrgId = req.query.organization_id as string | undefined;
    
    const user = await prisma.user.findFirst({
      where: { 
        id: userId,
        deleted_at: null,
      },
      select: {
        id: true,
        email: true,
        first_name: true,
        last_name: true,
        role: true,
        organization_id: true,
        status: true,
      },
    });

    if (!user) {
      return res.status(404).json({ error: "User not found" });
    }

    // SECURITY: Validate organization boundary if provided
    if (requestedOrgId && user.organization_id !== requestedOrgId) {
      console.warn(`⚠️ Organization boundary violation attempt: requested ${requestedOrgId}, user belongs to ${user.organization_id}`);
      return res.status(404).json({ error: "User not found" });
    }

    res.json({
      user: {
        _id: user.id,
        email: user.email,
        firstName: user.first_name,
        lastName: user.last_name,
        role: user.role,
        organizationId: user.organization_id,
        isEmailVerified: user.status === "active",
      },
    });
  } catch (error) {
    res.status(500).json({ error: "Internal server error" });
  }
});

router.get("/user-by-email/:email", async (req, res) => {
  try {
    const { email } = req.params;
    
    // SECURITY: Optional organization boundary check
    const requestedOrgId = req.query.organization_id as string | undefined;
    
    const whereClause: any = { email, deleted_at: null };
    
    // If organization_id is provided, enforce boundary
    if (requestedOrgId) {
      whereClause.organization_id = requestedOrgId;
    }
    
    const user = await prisma.user.findFirst({
      where: whereClause,
      select: {
        id: true,
        email: true,
        first_name: true,
        last_name: true,
        role: true,
        organization_id: true,
        status: true,
      },
    });

    if (!user) {
      return res.status(404).json({ error: "User not found" });
    }

    res.json({
      success: true,
      user: {
        _id: user.id,
        email: user.email,
        firstName: user.first_name,
        lastName: user.last_name,
        role: user.role,
        organizationId: user.organization_id,
        isEmailVerified: user.status === "active",
      },
    });
  } catch (error) {
    console.error("Error fetching user by email:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

export { router as internalRoutes };
