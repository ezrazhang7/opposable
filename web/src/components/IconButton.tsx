import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cx } from "../lib/ui";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  children: ReactNode;
  active?: boolean;
};

export function IconButton({ label, children, active, className, ...rest }: Props) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={cx(
        "grid h-8 w-8 shrink-0 place-items-center rounded-xl text-muted transition-colors",
        "hover:bg-raised hover:text-fg focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none",
        "disabled:pointer-events-none disabled:opacity-40",
        active && "bg-raised text-fg",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
