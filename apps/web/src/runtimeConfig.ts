import { setApiBaseUrl } from "./services";

const env = import.meta.env as Record<string, string | undefined>;

// The laptop publishes its current tunnel URL to this file (scripts/launch.py), so the
// deployed site finds the API without being rebuilt every time the tunnel changes.
async function discover(): Promise<string> {
  const configUrl = env.VITE_CONFIG_URL;
  if (configUrl) {
    try {
      const response = await fetch(`${configUrl}?t=${Date.now()}`, {
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      if (response.ok) {
        const body = await response.json();
        if (body.apiBaseUrl) return String(body.apiBaseUrl).replace(/\/$/, "");
        return "";
      }
    } catch {
      // fall through to the build-time URL
    }
  }
  return (env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
}

async function reachable(base: string): Promise<boolean> {
  try {
    const response = await fetch(`${base}/api/v1/health/ready`, {
      signal: AbortSignal.timeout(6000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

function showOffline(): void {
  const bar = document.createElement("div");
  bar.setAttribute("role", "alert");
  bar.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:9999;padding:10px 16px;background:#8a4b12;color:#fff;font:14px system-ui;text-align:center";
  bar.innerHTML =
    'The NAGARSAATHI server is offline right now. Start it on the host laptop, then <a href="" style="color:#fff;text-decoration:underline">reload</a>.';
  document.body.appendChild(bar);
}

export async function bootstrapApi(): Promise<void> {
  const base = await discover();
  setApiBaseUrl(base);
  if (base) {
    const original = window.fetch.bind(window);
    window.fetch = (input, init) =>
      typeof input === "string" && input.startsWith("/api")
        ? original(base + input, init)
        : original(input, init);
  }
  if (base ? !(await reachable(base)) : Boolean(env.VITE_CONFIG_URL))
    showOffline();
}
