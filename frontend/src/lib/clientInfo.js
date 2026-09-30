// Optional hints sent with a login so the "new login" email can show
// the right local time and say whether the installed app was used.
// Purely descriptive: the backend treats them as untrusted display
// text and never uses them for any security decision.
export function clientHints() {
  const hints = {};

  try {
    hints.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    hints.timezone = "";
  }

  try {
    hints.standalone =
      window.matchMedia?.("(display-mode: standalone)")?.matches === true ||
      window.navigator.standalone === true; // iOS home-screen app
  } catch {
    hints.standalone = false;
  }

  try {
    hints.platform = navigator.userAgentData?.platform || "";
  } catch {
    hints.platform = "";
  }

  return hints;
}
