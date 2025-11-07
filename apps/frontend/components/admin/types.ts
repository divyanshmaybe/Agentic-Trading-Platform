export type AdminSettingsForm = {
  users: { id: string; role: "admin" | "staff" | "viewer"; active: boolean }[];
};

export type AdminSettingsUserField = {
  id: string;
  name: string;
  email: string;
  roleField: `users.${number}.role`;
  activeField: `users.${number}.active`;
};

export type CreateUserFormValues = {
  email: string;
  password: string;
  firstName: string;
  lastName: string;
  role: "staff" | "viewer";
};

export type DirectoryUser = {
  id: string;
  name: string;
  email: string;
  role: "admin" | "staff" | "viewer";
  status: "active" | "suspended" | "inactive";
  lastActive: string;
};
