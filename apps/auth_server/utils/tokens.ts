import jwt from "jsonwebtoken";
import { prisma } from "../lib/prisma";

export const generateAccessToken = (userId: string, role: string, organizationId: string) => {
  return jwt.sign(
    { id: userId, role, organizationId },
    process.env.JWT_SECRET_ACCESS!,
    {
      expiresIn: "1d",
    }
  );
};

export const generateRefreshToken = (userId: string, role: string, organizationId: string) => {
  return jwt.sign(
    { id: userId, role, organizationId },
    process.env.JWT_SECRET_REFRESH!,
    {
      expiresIn: "7d",
    }
  );
};

export const generateTokens = async (userId: string) => {
  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: { id: true, role: true, organization_id: true },
  });

  if (!user) throw new Error("User not found");

  const accessToken = generateAccessToken(user.id, user.role, user.organization_id);
  const refreshToken = generateRefreshToken(user.id, user.role, user.organization_id);

  return { accessToken, refreshToken };
};
