import { Router } from "express";
import {
  protectRoute,
  isUser,
} from "../../../middleware/js/authMiddleware";
import {
  updateUserProfile,
  updateUserSubscriptions,
} from "../controllers/auth.controllers";

const userRoutes: Router = Router();

// User routes (any authenticated user)
userRoutes.post("/update", protectRoute, isUser, updateUserProfile);
userRoutes.post(
  "/subscriptions",
  protectRoute,
  isUser,
  updateUserSubscriptions
);

export { userRoutes };