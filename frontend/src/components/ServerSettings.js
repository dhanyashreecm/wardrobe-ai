import { useState } from "react";
import { API_URL, DEFAULT_API_URL, IS_NATIVE_APP, SERVER_KEY } from "../config";

// "Server" link on the login screen - lets the phone app point at the
// backend's https address. Shown inside the app, or when ?server is in
// the URL. The address is only stored on this phone.
export default function ServerSettings() {
  const notSet = IS_NATIVE_APP && /localhost|127\.0\.0\.1/.test(API_URL);
  const [open, setOpen] = useState(notSet);
  const [value, setValue] = useState(notSet ? "https://" : API_URL);
  const [status, setStatus] = useState("");
  const visible = IS_NATIVE_APP || window.location.search.includes("server");
  if (!visible) return null;

  const test = async (url) => {
    setStatus("Checking…");
    try {
      const res = await fetch(`${url.replace(/\/+$/, "")}/api/health`, { method: "GET" });
      setStatus(res.ok ? "✅ Connected" : `Server answered ${res.status}`);
      return res.ok;
    } catch {
      setStatus("❌ Can't reach that address");
      return false;
    }
  };

  const save = async () => {
    const url = value.trim().replace(/\/+$/, "");
    if (!/^https?:\/\/\S+$/.test(url)) { setStatus("Enter an address starting with https://"); return; }
    if (await test(url)) {
      try { localStorage.setItem(SERVER_KEY, url); } catch { /* private mode */ }
      window.location.reload();
    }
  };

  const reset = () => {
    try { localStorage.removeItem(SERVER_KEY); } catch { /* ignore */ }
    window.location.reload();
  };

  return (
    <div className="server-settings">
      <button type="button" className="server-link" onClick={() => setOpen((o) => !o)}>
        ⚙️ Server {open ? "▴" : "▾"}
      </button>
      {open && (
        <div className="server-box">
          {notSet && <p className="server-status">👋 First time? Enter your Wardrobe AI server address to start.</p>}
          <label htmlFor="server-url">Server address</label>
          <input id="server-url" value={value} onChange={(e) => setValue(e.target.value)}
            placeholder="https://your-name-wardrobe-ai.hf.space" autoCapitalize="none" autoCorrect="off" />
          <div className="server-actions">
            <button type="button" onClick={() => test(value.trim())}>Test</button>
            <button type="button" onClick={save}>Save</button>
            {API_URL !== DEFAULT_API_URL && <button type="button" onClick={reset}>Reset</button>}
          </div>
          {status && <p className="server-status">{status}</p>}
        </div>
      )}
    </div>
  );
}
