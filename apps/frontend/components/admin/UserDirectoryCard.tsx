import type { ComponentPropsWithoutRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import type { UserSummary } from "@/data/adminUsers";

type UserDirectoryCardProps = {
  title: string;
  description: string;
  users: UserSummary[];
  className?: string;
} & ComponentPropsWithoutRef<typeof Card>;

export function UserDirectoryCard({ title, description, users, className = "", ...cardProps }: UserDirectoryCardProps) {
  return (
    <Card className={`card-glass neon-hover rounded-2xl flex h-full flex-col ${className}`} {...cardProps}>
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
                <span className="text-xs text-white/50">{user.title}</span>
              </div>
              <div className="text-right text-xs text-white/60">
                <StatusBadge status={user.status} />
                <div className="mt-1">{user.lastActive}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-auto flex items-center justify-end gap-2 text-xs text-white/50">
          <span>Pagination ready</span>
          <span className="size-1 rounded-full bg-white/40" aria-hidden />
          <span>Showing {users.length} users</span>
        </div>
      </CardContent>
    </Card>
  );
}

type StatusBadgeProps = {
  status: UserSummary["status"];
};

function StatusBadge({ status }: StatusBadgeProps) {
  const isActive = status === "active";
  const badgeClass = isActive ? "bg-emerald-500/20 text-emerald-300" : "bg-amber-500/10 text-amber-200";

  return (
    <span className={`inline-flex items-center justify-center rounded-full px-2 py-0.5 text-[11px] font-medium ${badgeClass}`}>
      {isActive ? "Active" : "Invited"}
    </span>
  );
}

