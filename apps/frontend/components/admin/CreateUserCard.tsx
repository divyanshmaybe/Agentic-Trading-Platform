import type { ComponentPropsWithoutRef, FormEventHandler } from "react";
import type { FieldErrors, UseFormRegister } from "react-hook-form";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { CreateUserForm } from "./CreateUserForm";
import type { CreateUserFormValues } from "./types";

type CreateUserCardProps = {
  title?: string;
  register: UseFormRegister<CreateUserFormValues>;
  errors: FieldErrors<CreateUserFormValues>;
  onSubmit: FormEventHandler<HTMLFormElement>;
  isSubmitting: boolean;
  errorMessage?: string | null;
  successMessage?: string | null;
  className?: string;
} & ComponentPropsWithoutRef<typeof Card>;

export function CreateUserCard({
  title = "Create User",
  register,
  errors,
  onSubmit,
  isSubmitting,
  errorMessage,
  successMessage,
  className = "",
  ...cardProps
}: CreateUserCardProps) {
  return (
    <Card
      className={`card-glass rounded-2xl border border-white/10 bg-white/6 text-white/70 shadow-[0_32px_70px_-45px_rgba(0,0,0,0.95)] backdrop-blur flex h-full flex-col sm:col-span-2 lg:col-span-4 ${className}`}
      role="region"
      aria-label={title}
      {...cardProps}
    >
      <CardHeader>
        <CardTitle className="h-title text-xl">{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1">
        <CreateUserForm
          register={register}
          errors={errors}
          onSubmit={onSubmit as FormEventHandler<HTMLFormElement>}
          isSubmitting={isSubmitting}
          errorMessage={errorMessage}
          successMessage={successMessage}
        />
      </CardContent>
    </Card>
  );
}

