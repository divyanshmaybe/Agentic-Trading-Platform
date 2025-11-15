import { Router } from "express";
import {
  protectRoute,
  isStaff,
  isUser,
} from "../../../middleware/js/authMiddleware";
import {
  changePassword,
  createUser,
  getUsers,
  googleLogin,
  loginUser,
  logoutUser,
  refreshToken,
  registerOrganization,
  requestActivationEmail,
  requestPasswordEmail,
  updateUser,
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
authRoutes.get("/users", protectRoute, isStaff, getUsers);
authRoutes.patch("/users/:id", protectRoute, isStaff, updateUser);

export { authRoutes };
