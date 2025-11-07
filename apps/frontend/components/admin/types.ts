import type { Investor } from "@/lib/dashboardData";

export type AdminSettingsForm = {
  users: { id: string; role: NonNullable<Investor["role"]>; active: boolean }[];
};

export type AdminSettingsUserField = {
  id: string;
  name: string;
  value: string;
  roleField: `users.${number}.role`;
  activeField: `users.${number}.active`;
};

export type CreateUserFormValues = {
  email: string;
  password: string;
  firstName: string;
  lastName: string;
  role: "staff" | "customer";
};
