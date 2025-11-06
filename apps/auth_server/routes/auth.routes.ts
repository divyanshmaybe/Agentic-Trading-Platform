import { Router } from "express";
import {
  protectRoute,
  isAdmin,
  isStaff,
  isUser,
} from "../../../middleware/js/authMiddleware";
import {
  changePassword,
  createUser,
  googleLogin,
  loginUser,
  logoutUser,
  refreshToken,
  registerOrganization,
  requestActivationEmail,
  requestPasswordEmail,
  updateUserProfile,
  verifyEmail,
} from "../controllers/auth.controllers";

const authRoutes: Router = Router();

// Public routes (no authentication required)
authRoutes.post("/organizations/register", registerOrganization);
authRoutes.post("/login", loginUser);
authRoutes.post("/google-login", googleLogin);
authRoutes.post("/refresh-token", refreshToken);
authRoutes.post("/request-password-mail", requestPasswordEmail);
authRoutes.post("/request-activation-mail", requestActivationEmail);
authRoutes.post("/change-password", changePassword);
authRoutes.post("/verify-email", verifyEmail);

// Protected routes (authentication required)
authRoutes.post("/logout", protectRoute, isUser, logoutUser);

// Staff/Admin routes (staff or admin privileges required)
authRoutes.post("/users", protectRoute, isStaff, createUser);

// User routes (any authenticated user)
authRoutes.post("/user/update", protectRoute, isUser, updateUserProfile);

export { authRoutes };
