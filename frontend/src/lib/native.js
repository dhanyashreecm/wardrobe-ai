import { IS_NATIVE_APP } from "../config";

// Small touches that only apply inside the installed Android/iOS app.
export async function setupNativeShell() {
  if (!IS_NATIVE_APP) return;
  document.documentElement.classList.add("native-app");
  try {
    const { StatusBar, Style } = await import("@capacitor/status-bar");
    await StatusBar.setStyle({ style: Style.Light }); // dark icons on the cream bar
    if (window.Capacitor.getPlatform() === "android") {
      await StatusBar.setOverlaysWebView({ overlay: false });
      await StatusBar.setBackgroundColor({ color: "#FAF5F0" });
    }
  } catch {
    /* status bar plugin missing - harmless */
  }
}
