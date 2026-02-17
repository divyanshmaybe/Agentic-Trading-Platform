'use client';

import { type ComponentPropsWithoutRef, type FormEventHandler } from "react";
import type { UseFormRegister } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import type { AdminSettingsForm, AdminSettingsUserField } from "./types";

type CompanySettingsCardProps = {
  title?: string;
  users: AdminSettingsUserField[];
  register: UseFormRegister<AdminSettingsForm>;
  onSubmit: FormEventHandler<HTMLFormElement>;
  saving: boolean;
  errorMessage?: string | null;
  successMessage?: string | null;
  className?: string;
} & ComponentPropsWithoutRef<typeof Card>;

export function CompanySettingsCard({
  title = "Company Settings",
  users,
  register,
  onSubmit,
  saving,
  errorMessage,
  successMessage,
  className = "",
  ...cardProps
}: CompanySettingsCardProps) {
  return (
    <Card
      className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur flex h-full flex-col sm:col-span-1 lg:col-span-6 ${className}`}
      role="region"
      aria-label={title}
      {...cardProps}
    >
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex-1">
        <form onSubmit={onSubmit} className="space-y-4">
          {errorMessage && (
            <div className="rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm text-red-200" role="alert">
              {errorMessage}
            </div>
          )}
          {successMessage && (
            <div className="rounded-lg border border-emerald-400/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200" role="status">
              {successMessage}
            </div>
          )}
          <div className="space-y-3">
            {users.map((user) => (
              <div
                key={user.id}
                className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 p-3"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{user.name}</div>
                  <div className="hidden text-sm text-white/60 md:block" title={user.email}>
                    <span className="block wrap-break-word">{user.email}</span>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <select
                    {...register(user.roleField)}
                    className="rounded-md border border-white/10 bg-black/40 px-2.5 py-1.5 text-sm text-white focus:outline-none"
                    aria-label={`Role for ${user.name}`}
                  >
                    <option value="viewer">Viewer</option>
                    <option value="staff">Staff</option>
                    <option value="admin">Admin</option>
                  </select>
                  <label className="inline-flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      {...register(user.activeField)}
                      className="size-4 rounded border-white/20 bg-black/40 accent-white"
                      aria-label={`Active state for ${user.name}`}
                    />
                    <span className="text-white/80">Active</span>
                  </label>
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-end">
            <Button
              type="submit"
              disabled={saving}
              className="border border-white/10 bg-white/10 text-white hover:bg-white/20"
              aria-busy={saving}
            >
              {saving ? "Saving..." : "Save changes"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
