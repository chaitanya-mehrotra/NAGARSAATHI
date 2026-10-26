import { validateAnalysis } from "./validation";

export const configured = true;
export const supabase = null;

const base = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001").replace(/\/$/, "");

const TOKEN_KEY = "nagarsaathi_token";
const USER_KEY = "nagarsaathi_user";

export function reportPhotoUrl(path) {
  const apiOrigin = new URL(base, window.location.origin).origin;
  const url = new URL(path.startsWith("http") ? path : `${base}${path}`, window.location.origin);
  if (url.origin !== apiOrigin) throw new Error("Unexpected photo service origin");
  url.searchParams.set("token", getStoredToken());
  return url.toString();
}

export function getStoredToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function getStoredUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setSession(token, user) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export async function identity() {
  const token = getStoredToken();
  if (!token) return null;
  try {
    const user = await request("/auth/me");
    setSession(token, user);
    return { token, user };
  } catch {
    clearSession();
    return null;
  }
}

export async function register(name, email, password) {
  const response = await fetch(`${base}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email, password }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error?.message || data.detail || "Registration failed");
  }
  return data;
}

export async function login(email, password) {
  const response = await fetch(`${base}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error?.message || data.detail || "Invalid email or password");
  }
  setSession(data.access_token, data.user);
  return data;
}

export async function logout() {
  try {
    await request("/auth/logout", { method: "POST" });
  } catch {
    // Ignore network errors on logout
  }
  clearSession();
}

export async function request(path, options = {}) {
  const token = getStoredToken();
  const headers = { ...options.headers };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(base + path, {
    ...options,
    headers,
  });

  if (response.status === 204) {
    return null;
  }

  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("The reporting service returned an unreadable response.");
  }

  if (!response.ok) {
    const errorMsg = data.error?.message || data.detail || "The request could not be completed. Please retry.";
    throw new Error(typeof errorMsg === "string" ? errorMsg : "Request error");
  }
  return data;
}

export async function analyze(file, signal) {
  const form = new FormData();
  form.append("image", file);
  const raw = await request("/dev/detect", { method: "POST", body: form, signal });
  
  // Normalize detections to standard format for frontend boxes
  const normalized = {
    model_version: raw.model_version || "YOLO11n",
    image_width: raw.image_width,
    image_height: raw.image_height,
    detections: (raw.detections || []).map((d) => ({
      class_name: d.label || d.class_name || "pothole",
      confidence: d.confidence,
      bbox: d.bbox_xyxy || d.bbox || [0, 0, 0, 0],
    })),
  };
  return validateAnalysis(normalized);
}

export async function submit(form) {
  const body = new FormData();
  body.append("image", form.file);
  body.append("description", String(form.description || ""));
  body.append("latitude", String(form.latitude));
  body.append("longitude", String(form.longitude));
  body.append("issue_type", String(form.issue_type || "pothole"));

  return request("/reports", { method: "POST", body,
    headers: form.submissionKey ? { "Idempotency-Key": form.submissionKey } : {},
  });
}

export async function updateReport(id, reviewData) {
  return request(`/reports/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(reviewData),
  });
}
