import { Request } from "express";

export interface AuthenticatedRequest extends Request {
  user?: {
    _id: string;
    email: string;
    firstName: string;
    lastName: string;
    role: "admin" | "staff" | "viewer";
    organizationId: string;
    isEmailVerified: boolean;
  };
  body: any;
}
