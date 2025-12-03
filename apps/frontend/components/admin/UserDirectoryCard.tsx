import type { ComponentPropsWithoutRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import type { DirectoryUser } from "./types";

type UserDirectoryCardProps = {
  title: string;
  description: string;
  users: DirectoryUser[];
  className?: string;
} & ComponentPropsWithoutRef<typeof Card>;

export function UserDirectoryCard({ title, description, users, className = "", ...cardProps }: UserDirectoryCardProps) {
  return (
    <Card className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur flex h-full flex-col ${className}`} {...cardProps}>
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
        <p className="text-sm text-white/60">{description}</p>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="max-h-64 space-y-3 overflow-y-auto pr-2" role="list">
          {users.map((user) => (
            <div
              key={user.id}
              role="listitem"
              className="flex items-start justify-between gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3"
            >
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-sm font-medium text-white">{user.name}</span>
                <span className="truncate text-xs text-white/60">{user.email}</span>
                <span className="text-xs text-white/50 capitalize">{user.role}</span>
              </div>
              <div className="text-right text-xs text-white/60">
                <StatusBadge status={user.status} />
                <div className="mt-1">{user.lastActive}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-auto flex items-center justify-end gap-2 text-xs text-white/50">
          <span>Showing {users.length} users</span>
        </div>
      </CardContent>
    </Card>
  );
}

type StatusBadgeProps = {
  status: DirectoryUser["status"];
};

function StatusBadge({ status }: StatusBadgeProps) {
  const statusClasses: Record<DirectoryUser["status"], string> = {
    active: "bg-emerald-500/20 text-emerald-300",
    suspended: "bg-amber-500/20 text-amber-200",
    inactive: "bg-slate-500/20 text-slate-200",
  };

  const badgeClass = statusClasses[status];

  return (
    <span className={`inline-flex items-center justify-center rounded-full px-2 py-0.5 text-[11px] font-medium ${badgeClass}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

