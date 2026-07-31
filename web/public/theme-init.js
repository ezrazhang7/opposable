// Applied before first paint so the shell never flashes the wrong theme.
//
// A separate file rather than an inline <script> because the server sends a
// CSP of `default-src 'self'`, which blocks inline execution. The alternative
// — allowing 'unsafe-inline' for scripts — would weaken the policy across the
// whole app to save one request for a file this small.
(() => {
  const saved = localStorage.getItem("opposable.theme");
  const dark = saved
    ? saved === "dark"
    : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle("dark", dark);
})();
