import { Request, Response, NextFunction } from "express";
import jwt from "jsonwebtoken";
import bcrypt from "bcryptjs";
import { generateTokens } from "../utils/tokens";
import { ErrorHandling } from "../../../middleware/js/errorHandler";
import {
  sendActivationEmail,
  sendPasswordResetEmail,
  sendWelcomeEmail,
} from "../utils/emailUtils";
import { AuthenticatedRequest } from "../../../types/auth";
import { prisma } from "../lib/prisma";
import { OAuth2Client } from "google-auth-library";

export const registerOrganization = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  try {
    const {
      name,
      email,
      phone,
      address,
      registration_number,
      tax_id,
      admin,
    } = req.body;

    if (!name || !email || !admin) {
      return next(
        new ErrorHandling(
          "Organization name, email, and admin details are required",
          400
        )
      );
    }

    if (!admin.email || !admin.password || !admin.first_name || !admin.last_name) {
      return next(
        new ErrorHandling(
          "Admin email, password, first_name, and last_name are required",
          400
        )
      );
    }

    const existingOrg = await prisma.organization.findUnique({
      where: { email },
    });

    if (existingOrg) {
      return next(
        new ErrorHandling("Organization with this email already exists", 409)
      );
    }

    const existingUser = await prisma.user.findFirst({
      where: { email: admin.email },
    });

    if (existingUser) {
      return next(
        new ErrorHandling("User with this email already exists", 409)
      );
    }

    const passwordHash = await bcrypt.hash(admin.password, 12);

    const organization = await prisma.organization.create({
      data: {
        name,
        email,
        phone,
        address,
        registration_number,
        tax_id,
        status: "active",
        subscription_tier: "basic",
        users: {
          create: {
            email: admin.email,
            password_hash: passwordHash,
            first_name: admin.first_name,
            last_name: admin.last_name,
            role: "admin",
            status: "active",
          },
        },
      },
      include: {
        users: {
          where: { email: admin.email },
          take: 1,
        },
      },
    });

    const adminUser = organization.users[0];

    await sendActivationEmail(adminUser.id, adminUser.email);

    const { accessToken, refreshToken } = await generateTokens(adminUser.id);

    res.cookie("refreshToken", refreshToken, {
      httpOnly: true,
      maxAge: 7 * 24 * 60 * 60 * 1000,
      sameSite: "none",
      secure: process.env.NODE_ENV === "production",
      path: "/",
    });

    return res.status(201).json({
      success: true,
      data: {
        organization: {
          id: organization.id,
          name: organization.name,
          email: organization.email,
          status: organization.status,
        },
        admin: {
          id: adminUser.id,
          email: adminUser.email,
          role: adminUser.role,
        },
        access_token: accessToken,
        refresh_token: refreshToken,
      },
    });
  } catch (err: any) {
    if (err.code === "P2002") {
      return next(new ErrorHandling("Email already exists", 409));
    }
    next(err);
  }
};

export const loginUser = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  try {
    // Safety check for req.body
    if (!req.body) {
      return next(new ErrorHandling("Request body is missing", 400));
    }

    const { email, password, organization_id } = req.body;

    if (!email || !password) {
      return next(new ErrorHandling("Email and password are required", 400));
    }

    const whereClause: any = { email, deleted_at: null };
    if (organization_id) {
      whereClause.organization_id = organization_id;
    }

    const user = await prisma.user.findFirst({
      where: whereClause,
    });

    if (!user || !user.password_hash) {
      return next(new ErrorHandling("Invalid email or password", 401));
    }

    const isMatch = await bcrypt.compare(password, user.password_hash);
    if (!isMatch) {
      return next(new ErrorHandling("Invalid email or password", 401));
    }

    if (user.status !== "active") {
      return next(new ErrorHandling("Account is suspended or inactive", 401));
    }

    const { accessToken, refreshToken } = await generateTokens(user.id);

    await prisma.user.update({
      where: { id: user.id },
      data: { last_login_at: new Date() },
    });

    res.cookie("refreshToken", refreshToken, {
      httpOnly: true,
      maxAge: 7 * 24 * 60 * 60 * 1000,
      sameSite: "none",
      secure: process.env.NODE_ENV === "production",
      path: "/",
    });

    return res.status(200).json({
      success: true,
      data: {
        user: {
          id: user.id,
          role: user.role,
          email: user.email,
          first_name: user.first_name,
          last_name: user.last_name,
          organization_id: user.organization_id,
        },
        access_token: accessToken,
        refresh_token: refreshToken,
      },
    });
  } catch (err) {
    next(err);
  }
};

export const logoutUser = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  if (!(req as unknown as AuthenticatedRequest).user) {
    return next(new ErrorHandling("User not authenticated", 401));
  }

  res.clearCookie("refreshToken", {
    httpOnly: true,
    sameSite: "none",
    secure: process.env.NODE_ENV === "production",
  });

  return res.status(200).json({
    success: true,
    message: "User logged out successfully",
  });
};

export const refreshToken = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  try {
    const token = req.cookies.refreshToken || req.body.refresh_token;
    if (!token) {
      return next(new ErrorHandling("Refresh token not provided", 401));
    }

    let decoded: any;
    try {
      decoded = jwt.verify(token, process.env.JWT_SECRET_REFRESH!);
    } catch (err) {
      return next(new ErrorHandling("Invalid or expired refresh token", 401));
    }

    const user = await prisma.user.findUnique({
      where: { id: decoded.id },
    });

    if (!user || user.deleted_at) {
      return next(new ErrorHandling("User not found", 401));
    }

    const { accessToken, refreshToken: newRefreshToken } = await generateTokens(user.id);

    res.cookie("refreshToken", newRefreshToken, {
      httpOnly: true,
      maxAge: 7 * 24 * 60 * 60 * 1000,
      sameSite: "none",
      secure: process.env.NODE_ENV === "production",
      path: "/",
    });

    return res.status(200).json({
      success: true,
      data: {
        access_token: accessToken,
        refresh_token: newRefreshToken,
      },
    });
  } catch (err) {
    next(err);
  }
};

export const requestActivationEmail = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  try {
    const { email } = req.body;
    if (!email) {
      return next(new ErrorHandling("Email is required", 400));
    }

    const user = await prisma.user.findFirst({
      where: { email, deleted_at: null },
    });

    if (!user) {
      return next(new ErrorHandling("User with this email not found", 404));
    }

    await sendActivationEmail(user.id, user.email);

    return res.status(200).json({
      success: true,
      message: "Activation email sent successfully",
    });
  } catch (err) {
    next(err);
  }
};

export const requestPasswordEmail = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  try {
    const { email } = req.body;
    if (!email) {
      return next(new ErrorHandling("Email is required", 400));
    }

    const user = await prisma.user.findFirst({
      where: { email, deleted_at: null },
    });

    if (!user) {
      return next(new ErrorHandling("User with this email not found", 404));
    }

    await sendPasswordResetEmail(user.id, user.email, "reset");

    return res.status(200).json({
      success: true,
      message: "Password reset email sent successfully",
    });
  } catch (err) {
    next(err);
  }
};

export const verifyEmail = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  try {
    const { token } = req.body;
    if (!token) {
      return next(new ErrorHandling("Activation token is required", 400));
    }

    let decoded: any;
    try {
      decoded = jwt.verify(token, process.env.JWT_SECRET_EMAIL!);
    } catch (err: any) {
      if (err.name === "TokenExpiredError") {
        return next(new ErrorHandling("Activation token has expired", 400));
      }
      return next(new ErrorHandling("Activation token is incorrect", 400));
    }

    const user = await prisma.user.findUnique({
      where: { id: decoded.id },
    });

    if (!user) {
      return next(new ErrorHandling("User not found", 404));
    }

    await prisma.user.update({
      where: { id: user.id },
      data: { status: "active" },
    });

    sendWelcomeEmail(user.email, user.first_name).catch((error) => {
      console.error("Failed to send welcome email:", error);
    });

    return res.status(200).json({
      success: true,
      message: "Email verified successfully",
    });
  } catch (err) {
    next(err);
  }
};

export const changePassword = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  const { token, newPassword } = req.body;
  if (!token || !newPassword) {
    return next(new ErrorHandling("Token and new password are required", 400));
  }

  let decoded: any;
  try {
    decoded = jwt.verify(token, process.env.JWT_SECRET_EMAIL!);
  } catch (err: any) {
    if (err.name === "TokenExpiredError") {
      return next(new ErrorHandling("Token has expired", 400));
    }
    return next(new ErrorHandling("Invalid token", 400));
  }

  const user = await prisma.user.findUnique({
    where: { id: decoded.id },
  });

  if (!user) {
    return next(new ErrorHandling("User not found", 404));
  }

  const passwordHash = await bcrypt.hash(newPassword, 12);

  await prisma.user.update({
    where: { id: user.id },
    data: { password_hash: passwordHash },
  });

  return res.status(200).json({
    success: true,
    message: "Password changed successfully",
  });
};

export const createUser = async (
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
) => {
  try {
    const { email, password, first_name, last_name, role } = (req as any).body;

    if (!email || !password || !first_name || !last_name) {
      return next(
        new ErrorHandling(
          "Email, password, first_name, and last_name are required",
          400
        )
      );
    }

    const organizationId = (req as AuthenticatedRequest).user?.organizationId || (req as any).body.organization_id;
    if (!organizationId) {
      return next(new ErrorHandling("Organization ID is required", 400));
    }

    const existingUser = await prisma.user.findFirst({
      where: {
        email,
        organization_id: organizationId,
        deleted_at: null,
      },
    });

    if (existingUser) {
      return next(
        new ErrorHandling("User with this email already exists", 409)
      );
    }

    const passwordHash = await bcrypt.hash(password, 12);

    const user = await prisma.user.create({
      data: {
        email,
        password_hash: passwordHash,
        first_name,
        last_name,
        role: role || "staff",
        organization_id: organizationId,
        status: "active",
      },
    });

    await sendActivationEmail(user.id, user.email);

    return res.status(201).json({
      success: true,
      data: {
        id: user.id,
        role: user.role,
        email: user.email,
        first_name: user.first_name,
        last_name: user.last_name,
      },
    });
  } catch (err: any) {
    if (err.code === "P2002") {
      return next(new ErrorHandling("User already exists", 409));
    }
    next(err);
  }
};

export const updateUser = async (
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
) => {
  try {
    const userId = req.params.id;
    const { role, status } = req.body || {};

    if (!userId) {
      return next(new ErrorHandling("User ID is required", 400));
    }

    const organizationId = req.user?.organizationId;
    if (!organizationId) {
      return next(new ErrorHandling("Organization ID not found", 400));
    }

    const allowedRoles = ["admin", "staff", "viewer"];
    const allowedStatuses = ["active", "suspended", "inactive"];

    const updateData: Record<string, any> = {};

    if (typeof role !== "undefined") {
      if (role === "customer") {
        updateData.role = "viewer";
      } else if (allowedRoles.includes(role)) {
        updateData.role = role;
      } else {
        return next(
          new ErrorHandling("Role must be one of: admin, staff, viewer", 400)
        );
      }
    }

    if (typeof status !== "undefined") {
      if (!allowedStatuses.includes(status)) {
        return next(
          new ErrorHandling(
            "Status must be one of: active, suspended, inactive",
            400
          )
        );
      }
      updateData.status = status;
    }

    if (!Object.keys(updateData).length) {
      return next(
        new ErrorHandling("At least one of role or status must be provided", 400)
      );
    }

    const existingUser = await prisma.user.findFirst({
      where: {
        id: userId,
        organization_id: organizationId,
        deleted_at: null,
      },
    });

    if (!existingUser) {
      return next(new ErrorHandling("User not found", 404));
    }

    const updatedUser = await prisma.user.update({
      where: { id: userId },
      data: updateData,
      select: {
        id: true,
        email: true,
        first_name: true,
        last_name: true,
        role: true,
        status: true,
        phone: true,
        last_login_at: true,
        two_factor_enabled: true,
        created_at: true,
        updated_at: true,
      },
    });

    return res.status(200).json({
      success: true,
      data: updatedUser,
    });
  } catch (err) {
    next(err);
  }
};

export const updateUserProfile = async (
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
) => {
  try {
    const userId = (req as AuthenticatedRequest).user?._id;
    const { first_name, last_name, phone } = req.body;

    if (!userId) {
      return next(new ErrorHandling("User not authenticated", 401));
    }

    const updateData: any = {};
    if (first_name) updateData.first_name = first_name;
    if (last_name) updateData.last_name = last_name;
    if (phone) updateData.phone = phone;

    const updatedUser = await prisma.user.update({
      where: { id: userId },
      data: updateData,
    });

    return res.status(200).json({
      success: true,
      data: {
        id: updatedUser.id,
        email: updatedUser.email,
        first_name: updatedUser.first_name,
        last_name: updatedUser.last_name,
        phone: updatedUser.phone,
        role: updatedUser.role,
      },
    });
  } catch (err) {
    next(err);
  }
};

export const googleLogin = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  try {
    const { credential, organization_id } = req.body;

    if (!credential) {
      return next(new ErrorHandling("Google credential is required", 400));
    }

    const googleClient = new OAuth2Client(
      process.env.GOOGLE_CLIENT_ID || process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID
    );

    try {
      const ticket = await googleClient.verifyIdToken({
        idToken: credential,
        audience:
          process.env.GOOGLE_CLIENT_ID ||
          process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID,
      });

      const payload = ticket.getPayload();
      if (!payload) {
        return next(new ErrorHandling("Invalid Google token", 401));
      }

      const { sub: googleId, email, picture, family_name, given_name } =
        payload;

      if (!email) {
        return next(new ErrorHandling("Email not provided by Google", 400));
      }

      // Find user in database
      let user = await prisma.user.findFirst({
        where: {
          email,
          deleted_at: null,
        },
        include: {
          organization: true,
        },
      });

      // If organization_id is provided, ensure user belongs to it
      if (organization_id) {
        if (user && user.organization_id !== organization_id) {
          return next(
            new ErrorHandling(
              "User does not belong to the specified organization",
              403
            )
          );
        }
      }

      // If user doesn't exist, they need to register first
      if (!user) {
        return next(
          new ErrorHandling(
            "User not found. Please register your organization first.",
            404
          )
        );
      }

      // Update last login
      await prisma.user.update({
        where: { id: user.id },
        data: { last_login_at: new Date() },
      });

      // Generate tokens
      const { accessToken, refreshToken } = await generateTokens(user.id);

      res.cookie("refreshToken", refreshToken, {
        httpOnly: true,
        maxAge: 7 * 24 * 60 * 60 * 1000,
        sameSite: "none",
        secure: process.env.NODE_ENV === "production",
        path: "/",
      });

      return res.status(200).json({
        success: true,
        data: {
          user: {
            id: user.id,
            email: user.email,
            first_name: user.first_name,
            last_name: user.last_name,
            role: user.role,
            organization_id: user.organization_id,
            organization: {
              id: user.organization.id,
              name: user.organization.name,
              email: user.organization.email,
            },
          },
          access_token: accessToken,
          refresh_token: refreshToken,
        },
      });
    } catch (error: any) {
      console.error("Google auth error:", error);
      return next(new ErrorHandling("Google authentication failed", 401));
    }
  } catch (err) {
    next(err);
  }
};

export const getUsers = async (
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
) => {
  try {
    // Get authenticated user's organization_id
    const organizationId = req.user?.organizationId;
    if (!organizationId) {
      return next(new ErrorHandling("Organization ID not found", 400));
    }

    // Parse query parameters
    const page = parseInt(req.query.page as string) || 1;
    const limit = parseInt(req.query.limit as string) || 10;
    const role = req.query.role as string | undefined; // 'admin' | 'staff' | 'viewer'
    const status = req.query.status as string | undefined; // 'active' | 'suspended' | 'inactive'
    const search = req.query.search as string | undefined; // Search by email, first_name, or last_name

    // Validate pagination
    if (page < 1) {
      return next(new ErrorHandling("Page must be greater than 0", 400));
    }
    if (limit < 1 || limit > 100) {
      return next(new ErrorHandling("Limit must be between 1 and 100", 400));
    }

    // Validate role filter
    if (role && !["admin", "staff", "viewer"].includes(role)) {
      return next(
        new ErrorHandling("Role must be one of: admin, staff, viewer", 400)
      );
    }

    // Validate status filter
    if (status && !["active", "suspended", "inactive"].includes(status)) {
      return next(
        new ErrorHandling(
          "Status must be one of: active, suspended, inactive",
          400
        )
      );
    }

    // Build where clause
    const where: any = {
      organization_id: organizationId, // Filter by authenticated user's organization
      deleted_at: null, // Only non-deleted users
    };

    // Add role filter
    // When role=staff, include both staff and admin (since admins are also staff)
    if (role) {
      if (role === "staff") {
        // Staff filter should include both staff and admin roles
        where.role = { in: ["staff", "admin"] };
      } else {
        // For admin or viewer, filter by exact role
        where.role = role;
      }
    }

    // Add status filter
    if (status) {
      where.status = status;
    }

    // Add search filter (email, first_name, or last_name)
    if (search) {
      where.OR = [
        { email: { contains: search, mode: "insensitive" } },
        { first_name: { contains: search, mode: "insensitive" } },
        { last_name: { contains: search, mode: "insensitive" } },
      ];
    }

    // Calculate skip
    const skip = (page - 1) * limit;

    // Get total count for pagination metadata
    const total = await prisma.user.count({ where });

    // Fetch users with pagination
    const users = await prisma.user.findMany({
      where,
      skip,
      take: limit,
      orderBy: { created_at: "desc" },
      select: {
        id: true,
        email: true,
        first_name: true,
        last_name: true,
        phone: true,
        role: true,
        status: true,
        last_login_at: true,
        two_factor_enabled: true,
        created_at: true,
        updated_at: true,
        // Exclude sensitive fields: password_hash, two_factor_secret, metadata
      },
    });

    // Calculate pagination metadata
    const totalPages = Math.ceil(total / limit);
    const hasNextPage = page < totalPages;
    const hasPrevPage = page > 1;

    return res.status(200).json({
      success: true,
      data: {
        users,
        pagination: {
          page,
          limit,
          total,
          totalPages,
          hasNextPage,
          hasPrevPage,
        },
        filters: {
          role: role || null,
          status: status || null,
          search: search || null,
        },
      },
    });
  } catch (err) {
    next(err);
  }
};
