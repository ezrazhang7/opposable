import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { ArrowUp, Spinner } from "./Icons";
import { cx } from "../lib/ui";

type Props = {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  placeholder?: string;
  disabled?: boolean;
  pending?: boolean;
  autoFocus?: boolean;
  minRows?: number;
  maxHeight?: number;
  /** Bottom rail: pickers on Home, controls in the chat column. */
  rail?: ReactNode;
  submitLabel?: string;
};

/** One composer, two homes: the big card on Home and the follow-up box under
 *  the chat stream. Enter submits, Shift+Enter breaks the line. */
export function Composer({
  value,
  onChange,
  onSubmit,
  placeholder = "Describe a task…",
  disabled,
  pending,
  autoFocus,
  minRows = 3,
  maxHeight = 260,
  rail,
  submitLabel = "Start task",
}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, [value, maxHeight]);

  const submit = () => {
    if (!value.trim() || disabled || pending) return;
    onSubmit();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div
      className={cx(
        "rounded-2xl border border-line bg-panel transition-colors",
        "focus-within:border-accent",
      )}
    >
      <textarea
        ref={ref}
        rows={minRows}
        value={value}
        autoFocus={autoFocus}
        disabled={disabled}
        placeholder={placeholder}
        aria-label={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        className="block w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-[14px] placeholder:text-faint focus:outline-none disabled:opacity-60"
      />
      <div className="flex items-center gap-2 px-3 pt-1 pb-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{rail}</div>
        <button
          type="button"
          onClick={submit}
          disabled={!value.trim() || disabled || pending}
          title={submitLabel}
          aria-label={submitLabel}
          className={cx(
            "grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-accent text-accent-fg transition-colors",
            "hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none",
            "disabled:cursor-not-allowed disabled:bg-line disabled:text-faint",
          )}
        >
          {pending ? <Spinner /> : <ArrowUp />}
        </button>
      </div>
    </div>
  );
}

/** The compact select used on composer rails. */
export function RailSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex items-center gap-1.5 rounded-xl border border-line px-2.5 py-1.5 text-[12px] text-muted transition-colors focus-within:border-accent hover:border-line-strong">
      <span className="text-faint">{label}</span>
      <select
        value={value}
        aria-label={label}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-[170px] cursor-pointer truncate bg-transparent text-fg focus:outline-none"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value} className="bg-panel text-fg">
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
