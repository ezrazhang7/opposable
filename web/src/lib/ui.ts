/** Tiny class-name joiner; conditional classes are `cond && "..."`. */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
