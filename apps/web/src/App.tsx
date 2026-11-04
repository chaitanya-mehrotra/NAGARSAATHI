import React, { useState, useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router";
import {
  LayoutDashboard,
  Map as MapIcon,
  FileText,
  Plus,
  Search,
  ArrowUpRight,
  ArrowRight,
  MapPin,
  Construction,
  Droplets,
  Check,
  CheckCheck,
  Info,
  ChevronRight,
  ChevronLeft,
  X,
  Upload,
  ShieldCheck,
  Menu,
  Clock,
  Copy,
  ExternalLink,
  RefreshCw,
  LoaderCircle,
  AlertTriangle,
  Trash2,
} from "lucide-react";
import ComplaintMap, { MapRow } from "./components/ComplaintMap";
import { IssueCounts, GroupingControls } from "./components/Grouping";
import { Splash } from "./components/Splash";
import {
  identity,
  request,
  loginWithGoogle,
  loginWithDemo,
  getAuthOptions,
  logout,
  getStoredUser,
  getStoredToken,
  StoredUser,
  reportPhotoUrl,
  deduplicateKeepOne,
  YoloAnalysisResult,
  calculatePriorityScore,
} from "./services";
import { CountUp } from "./motion";
import { useI18n } from "./i18n";
import { nearbyLandmark } from "./geocode";
import "./style.css";
import "./design.css";

export const issueLabels: Record<string, string> = {
  electric_pole_fallen: "Fallen Electric Pole / Live Wires",
  pothole: "Pothole",
  waterlogging: "Waterlogging",
  both: "Both issues",
  garbage_accumulation: "Garbage Accumulation",
  sewage_overflow: "Sewage Overflow",
  streetlight_failure: "Streetlight Failure",
  other_civic_issue: "Other Civic Issue",
};

export const statusLabels: Record<string, string> = {
  awaiting_review: "Under review",
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
  out_of_scope: "Out of scope",
  rejected: "Rejected",
};

// The stages a report can show, in lifecycle order (matches the API's display status).
const stages = Object.keys(statusLabels);
// Reviewers move a report between these before it is accepted, and its issue between these after.
const reviewStatuses = ["awaiting_review", "out_of_scope", "rejected"];
const acceptedStatuses = ["open", "in_progress", "resolved"];

const nav: [string, any][] = [
  ["Overview", LayoutDashboard],
  ["Report Issue", Plus],
  ["Complaint Map", MapIcon],
  ["My Reports", FileText],
];

const pagePaths: Record<string, string> = {
  Overview: "/",
  "Report Issue": "/report",
  "Complaint Map": "/map",
  "My Reports": "/my-reports",
};

const fresh = () => ({
  issue_type: "pothole",
  seriousness: "standard" as "critical_hazard" | "standard" | "minor",
  description: "",
  file: null as File | null,
  latitude: 12.9172,
  longitude: 77.6228,
  landmark: "",
  // Once the citizen types in the landmark field, the map lookup stops overwriting it.
  landmarkEdited: false,
  confirmed: true,
  analysis: null as YoloAnalysisResult | null,
  forceMismatch: false,
});

/** Photos need the bearer token, which a plain <img src> cannot send: fetch and show a blob. */
function AuthImage({ src, alt, className }: { src: string; alt: string; className?: string }) {
  const { t } = useI18n();
  const [url, setUrl] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let objectUrl = "";
    let active = true;
    setUrl("");
    setFailed(false);
    fetch(src, { headers: { Authorization: `Bearer ${getStoredToken()}` } })
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.blob();
      })
      .then((blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);
  if (failed) return <p className="location-line">{t("photo.missing")}</p>;
  return url ? <img className={className} src={url} alt={alt} /> : null;
}

/** The API returns nested counts; the dashboard tiles read flat keys. */
function flattenMetrics(m: any): Record<string, number> {
  if (!m?.reports) return m;
  const reports = m.reports;
  const issues = m.issues ?? {};
  const categories = m.categories ?? {};
  return {
    total: reports.total ?? 0,
    pothole: categories.pothole ?? 0,
    waterlogging: categories.waterlogging ?? 0,
    suspicious: reports.suspicious ?? 0,
    // Stage counts use the same rule as the list's status filter, so they always agree.
    ...Object.fromEntries(stages.map((s) => [s, m.stages?.[s] ?? 0])),
  };
}

export function App() {
  // Each page has its own address, so refresh and the Back button keep you where you were.
  const location = useLocation();
  const navigate = useNavigate();
  const { t, lang, setLang, locale } = useI18n();
  const issueName = (k: string) => (issueLabels[k] ? t(`issue.${k}`) : k);
  const statusName = (k: string) => (statusLabels[k] ? t(`status.${k}`) : k);
  const page =Object.keys(pagePaths).find((p) => pagePaths[p] === location.pathname) ?? "Overview";
  const [mobile, setMobile] = useState<boolean>(false);
  const [search, setSearch] = useState<string>("");
  const [issue, setIssue] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [date, setDate] = useState<string>("");
  const [until, setUntil] = useState<string>("");
  const [sort, setSort] = useState<string>("priority");
  const [view, setView] = useState<"map" | "list">("map");
  const [rows, setRows] = useState<any[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [metrics, setMetrics] = useState<any>(null);
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [connection] = useState<string>("Live");
  const [selected, setSelected] = useState<any | null>(null);
  const [detail, setDetail] = useState<any | null>(null);
  const [toast, setToast] = useState<string>("");
  const [refresh, setRefresh] = useState<number>(0);
  const [offset, setOffset] = useState<number>(0);

  // Authentication State
  const [user, setUser] = useState<StoredUser | null>(getStoredUser);
  const isAdmin = user?.role === "admin";
  const isNigam = user?.role === "nigam" || isAdmin;
  const [authModal, setAuthModal] = useState<boolean>(false);
  const [authTab, setAuthTab] = useState<"login" | "demo">("login");
  const [gsiAttempt, setGsiAttempt] = useState(0);
  const [authOptions, setAuthOptions] = useState<{ google_client_id: string | null; demo_enabled: boolean }>({
    google_client_id: null,
    demo_enabled: false,
  });
  useEffect(() => {
    getAuthOptions().then(setAuthOptions);
  }, []);
  const [authError, setAuthError] = useState<string>("");
  const [authLoading, setAuthLoading] = useState<boolean>(false);

  // Admin Review and Soft-Delete State
  const [reviewForm, setReviewForm] = useState({
    status: "open",
    priority: "normal",
    priority_reason: "",
  });
  const [reviewSaving, setReviewSaving] = useState<boolean>(false);
  const [deleteModal, setDeleteModal] = useState<boolean>(false);
  const [deleteReason, setDeleteReason] = useState<string>("");
  const [deleteBusy, setDeleteBusy] = useState<boolean>(false);

  // Reporting Wizard State
  const [form, setForm] = useState(fresh);
  const [step, setStep] = useState<number>(1);
  const [formError, setFormError] = useState<string>("");
  const [saving, setSaving] = useState<boolean>(false);
  const [preview, setPreview] = useState<string>("");
  const [success, setSuccess] = useState<any | null>(null);
  const [landmarkLookup, setLandmarkLookup] = useState<"idle" | "looking" | "found" | "failed">("idle");
  const [suggestedLandmark, setSuggestedLandmark] = useState("");

  const fileInput = useRef<HTMLInputElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const reload = () => setRefresh((x) => x + 1);

  const changePage = (p: string) => {
    if (pagePaths[p] !== location.pathname) navigate(pagePaths[p]);
    setMobile(false);
    setOffset(0);
  };

  const report = () => {
    if (!isNigam) return changePage("Report Issue");
    // Staff are usually already on Overview, so navigating alone does nothing visible:
    // switch to the list view and scroll the complaint list into view.
    changePage("Overview");
    setView("list");
    setTimeout(() => {
      document.getElementById("complaints")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 50);
  };

  function notify(t: string) {
    setToast(t);
    setTimeout(() => setToast(""), 4000);
  }

  // Load session on startup
  useEffect(() => {
    identity().then((sess) => {
      if (sess?.user) {
        setUser(sess.user);
      } else {
        setUser(null);
      }
    });
  }, []);

  // Update preview URL when photo changes
  useEffect(() => {
    if (!form.file) {
      setPreview("");
      return;
    }
    const url = URL.createObjectURL(form.file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [form.file]);

  // Suggest a nearby landmark for the pin. Waits for the pin to settle, cancels stale lookups,
  // and never overwrites a landmark the citizen typed themselves.
  const onLocationStep = page === "Report Issue" && step === 2 && !success;
  useEffect(() => {
    if (!onLocationStep) return;
    const lat = Number(form.latitude);
    const lng = Number(form.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return;
    const controller = new AbortController();
    setLandmarkLookup("looking");
    const timer = setTimeout(() => {
      nearbyLandmark(lat, lng, lang, controller.signal)
        .then((name) => {
          setSuggestedLandmark(name ?? "");
          setLandmarkLookup(name ? "found" : "failed");
          if (name) setForm((f) => (f.landmarkEdited ? f : { ...f, landmark: name }));
        })
        .catch((e) => {
          if (e?.name !== "AbortError") setLandmarkLookup("failed");
        });
    }, 600);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [onLocationStep, form.latitude, form.longitude, lang]);

  // Fetch complaints and metrics
  useEffect(() => {
    let active = true;
    setBusy(true);

    const params = new URLSearchParams({
      search,
      issue,
      status,
      since: date,
      until,
      sort,
      offset: String(offset),
      limit: "40",
      mine: String(page === "My Reports"),
    });

    const timer = setTimeout(() => {
      // The counters are public; the list itself needs an account.
      const counters = request("/api/v1/metrics").then((m) => {
        if (active && m) setMetrics(flattenMetrics(m));
      });
      const list = user
        ? request(`/api/v1/complaints?${params.toString()}`).then((data) => {
            if (active) {
              setRows(data.items || []);
              setTotal(data.total ?? 0);
            }
          })
        : Promise.resolve().then(() => {
            if (active) {
              setRows([]);
              setTotal(null);
            }
          });
      Promise.all([counters, list])
        .then(() => active && setError(""))
        .catch((e) => active && setError(e.message))
        .finally(() => active && setBusy(false));
    }, 150);

    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [search, issue, status, date, until, sort, page, offset, refresh, user]);

  // A different account (or none) must not see the previous one's list, drawer or draft report.
  const sessionKey = user?.id ?? null;
  const firstSession = useRef(true);
  useEffect(() => {
    if (firstSession.current) {
      firstSession.current = false;
      return;
    }
    setRows([]);
    setTotal(null);
    setSelected(null);
    setDetail(null);
    setForm(fresh());
    setStep(1);
    setSuccess(null);
    setFormError("");
  }, [sessionKey]);

  // Escape closes the top-most dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (deleteModal) setDeleteModal(false);
      else if (authModal) setAuthModal(false);
      else if (detail) closeDetails();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deleteModal, authModal, detail]);

  // Move keyboard focus into the drawer when it opens.
  useEffect(() => {
    if (detail) closeRef.current?.focus();
  }, [detail?.id]);

  // Sync review form when detail changes
  useEffect(() => {
    if (detail) {
      setReviewForm({
        status: detail.status || "open",
        priority: detail.priority || "normal",
        priority_reason: detail.priority_reason || "",
      });
    }
  }, [detail]);

  // Demo Login Handler
  async function handleDemoLogin(type: "admin" | "citizen") {
    setAuthError("");
    setAuthLoading(true);
    try {
      const res = await loginWithDemo(type);
      setUser(res.user);
      setDetail(null);
      setRows([]);
      if (res.user.role === "admin" || res.user.role === "nigam") {
        changePage("Overview");
      }
      setAuthModal(false);
      notify(t("toast.signedInAs", { name: res.user.name }));
      reload();
    } catch (err: any) {
      setAuthError(err.message || t("err.demoLogin"));
    } finally {
      setAuthLoading(false);
    }
  }

  // Google Identity Services (GSI) API integration
  useEffect(() => {
    if (authModal && authTab === "login" && authOptions.google_client_id) {
      let cancelled = false;
      const initGsi = async () => {
        const gsi = (window as any).google?.accounts?.id;
        if (gsi) {
          try {
            // One-use server nonce: the Google token must carry it back to be accepted.
            const { nonce } = await request("/api/v1/auth/google/challenge", { method: "POST" });
            if (cancelled) return;
            gsi.initialize({
              client_id: authOptions.google_client_id,
              nonce,
              callback: handleGoogleCredentialResponse,
            });
            const slot = document.getElementById("gsi-button-slot");
            if (slot) {
              slot.innerHTML = "";
              gsi.renderButton(slot, {
                theme: "outline",
                size: "large",
                type: "standard",
                shape: "rectangular",
                text: "continue_with",
                width: 360,
                locale: lang,
              });
            }
          } catch (e) {
            console.warn("GSI init info:", e);
          }
        }
      };
      const t = setTimeout(initGsi, 120);
      return () => {
        cancelled = true;
        clearTimeout(t);
      };
    }
  }, [authModal, authTab, authOptions.google_client_id, gsiAttempt, lang]);

  async function handleGoogleCredentialResponse(response: any) {
    if (!response?.credential) return;
    setAuthError("");
    setAuthLoading(true);
    try {
      const res = await loginWithGoogle({ credential: response.credential });
      setUser(res.user);
      setAuthModal(false);
      notify(t("toast.signedInGoogle", { name: res.user.name }));
      reload();
    } catch (err: any) {
      setAuthError(err.message || t("err.googleLogin"));
    } finally {
      setAuthLoading(false);
      setGsiAttempt((n) => n + 1); // the used nonce is spent; fetch a new one
    }
  }

  // Admin Direct Duplicate Cleanup from List
  async function triggerDeduplicateForReport(report: any) {
    if (!window.confirm(t("confirm.dedup", { ref: report.public_reference || report.id.slice(0, 8) }))) {
      return;
    }
    try {
      const res = await deduplicateKeepOne(report.id);
      notify(res.message || t("toast.dedupDone"));
      reload();
    } catch (e: any) {
      notify(t("toast.dedupFailed", { msg: e.message }));
    }
  }

  // Logout Handler
  async function handleLogout() {
    await logout();
    setUser(null);
    setDetail(null);
    notify(t("toast.signedOut"));
    reload();
  }

  // File selection
  function chooseFile(file: File) {
    if (file.size > 15 * 1024 * 1024) {
      setFormError(t("err.photoSize"));
      return;
    }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setFormError(t("err.photoType"));
      return;
    }
    setFormError("");
    // Photo verification runs on the server after submission; the browser never fakes a verdict.
    setForm((f) => ({ ...f, file, analysis: null }));
  }

  // Wizard step navigation
  function nextStep() {
    if (step === 1) {
      if (form.description.trim().length < 5) {
        setFormError(t("err.desc"));
        return;
      }
      setFormError("");
      setStep(2);
    } else if (step === 2) {
      if (!form.file) {
        setFormError(t("err.photo"));
        return;
      }
      if (!form.latitude || !form.longitude) {
        setFormError(t("err.pin"));
        return;
      }
      const lat = Number(form.latitude);
      const lng = Number(form.longitude);
      if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) {
        setFormError(t("err.coords"));
        return;
      }
      setFormError("");
      setStep(3);
    }
  }

  // Submit Complaint
  async function submitComplaint() {
    if (!user) {
      setAuthModal(true);
      notify(t("toast.signInFirst"));
      return;
    }
    setSaving(true);
    setFormError("");

    try {
      // 1. Upload photo
      const uploadRes = await request("/api/v1/uploads", {
        method: "POST",
        headers: { "Content-Type": form.file!.type },
        body: form.file,
      });
      // The server must verify and mark the upload ready before a report can use it.
      await request(`/api/v1/uploads/${uploadRes.id}/complete`, { method: "POST" });

      // 2. Submit report
      const idempotencyKey = crypto.randomUUID();
      const reportRes = await request("/api/v1/reports", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify({
          description: form.description,
          claimed_category: form.issue_type,
          media_ids: [uploadRes.id],
          location: {
            longitude: form.longitude,
            latitude: form.latitude,
            confirmed: form.confirmed,
          },
          location_source: "confirmed_pin",
          address_text: form.landmark.trim() || undefined,
          language_hint: lang,
        }),
      });

      setSuccess(reportRes);
      notify(t("toast.submitted"));
      setForm(fresh());
      setStep(1);
      setLandmarkLookup("idle");
      setSuggestedLandmark("");
      reload();
    } catch (err: any) {
      setFormError(err.message || t("err.submit"));
    } finally {
      setSaving(false);
    }
  }

  // Admin Save Review
  async function handleSaveReview() {
    if (!detail) return;
    setReviewSaving(true);
    try {
      const updated = await request(`/api/v1/complaints/${detail.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: reviewForm.status,
          priority: reviewForm.priority,
          priority_reason: reviewForm.priority_reason,
        }),
      });
      setDetail((d: any) => ({ ...d, ...updated }));
      notify(t("toast.reviewSaved"));
      reload();
    } catch (e: any) {
      notify(t("toast.reviewFailed", { msg: e.message }));
    } finally {
      setReviewSaving(false);
    }
  }

  // Admin Soft Delete
  async function handleSoftDelete() {
    if (!detail) return;
    if (!deleteReason.trim()) {
      notify(t("toast.reasonRequired"));
      return;
    }
    setDeleteBusy(true);
    try {
      await request(`/api/v1/reports/${detail.id}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: deleteReason }),
      });
      notify(t("toast.deleted"));
      setDeleteModal(false);
      setDeleteReason("");
      setDetail(null);
      reload();
    } catch (e: any) {
      notify(t("toast.deleteFailed", { msg: e.message }));
    } finally {
      setDeleteBusy(false);
    }
  }

  // Admin Deduplicate: Keep 1 & Delete All Duplicates
  async function handleDeduplicateKeepOne() {
    if (!detail) return;
    if (!window.confirm(t("confirm.dedup", { ref: detail.public_reference || detail.id }))) {
      return;
    }

    try {
      const res = await deduplicateKeepOne(detail.id);
      notify(res.message || t("toast.dedupDone"));
      const updated = await request(`/api/v1/complaints/${detail.id}`);
      setDetail(updated);
      reload();
    } catch (e: any) {
      notify(t("toast.dedupFailed", { msg: e.message }));
    }
  }

  const returnFocus = useRef<HTMLElement | null>(null);

  // Show the list row at once, then merge in the full record. Citizens may only fetch
  // their own reports' details, so for anyone else's the row is all there is.
  const openDetails = (r: any) => {
    returnFocus.current = document.activeElement as HTMLElement | null;
    setDetail(r);
    request(`/api/v1/complaints/${r.id}`)
      .then((full) => setDetail((d: any) => (d?.id === r.id ? { ...r, ...full } : d)))
      .catch(() => {});
  };

  const closeDetails = () => {
    setDetail(null);
    returnFocus.current?.focus();
  };

  const filterActive = search || issue || status || date || until;
  const clearFilters = () => {
    setSearch("");
    setIssue("");
    setStatus("");
    setDate("");
    setUntil("");
  };

  const statIcons = [FileText, Construction, Droplets, CheckCheck];
  const statCards = [
    [t("stat.total"), "total", t("stat.total.sub"), ""],
    [t("stat.pothole"), "pothole", t("stat.pothole.sub"), "pothole"],
    [t("stat.waterlogging"), "waterlogging", t("stat.waterlogging.sub"), "waterlogging"],
    [t("stat.resolved"), "resolved", t("stat.resolved.sub"), "resolved"],
  ];

  return (
    <div className="app">
      <Splash />

      {/* SIDEBAR */}
      <aside className={"sidebar " + (mobile ? "open" : "")}>
        <a
          href="#"
          className="brand"
          onClick={(e) => {
            e.preventDefault();
            changePage("Overview");
          }}
        >
          <span className="brand-symbol">
            <MapPin size={24} />
          </span>
          <span>
            NagarSaathi<small>{t("brand.tagline")}</small>
          </span>
        </a>

        <div className={"workspace-label" + (isAdmin ? " admin" : "")}>
          {isAdmin ? t("workspace.admin") : isNigam ? t("workspace.nigam") : t("workspace.citizen")}
        </div>

        <nav
          className="side-nav"
          style={{ "--active": Math.max(0, nav.findIndex(([p]) => p === page)) } as React.CSSProperties}
        >
          <span className="lane-marker" aria-hidden="true" />
          {nav.map(([p, Icon]) => (
            <button
              key={p}
              className={"nav-item " + (page === p ? "active" : "")}
              aria-current={page === p ? "page" : undefined}
              onClick={() => changePage(p)}
            >
              <Icon size={18} />
              {t(`nav.${p}`)}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="together">
            <span className="mini-icon">
              <ShieldCheck size={22} />
            </span>
            <h3>
              {t("side.title1")}
              <br />
              {t("side.title2")}
            </h3>
            <p>{t("side.body")}</p>
            <button onClick={report}>
              {isAdmin ? t("side.viewAll") : t("side.cta")}{" "}
              <ArrowRight size={15} />
            </button>
          </div>

          <div
            className={"session" + (user ? "" : " signed-out")}
            onClick={() => (!user ? setAuthModal(true) : null)}
          >
            <span className={"avatar" + (isAdmin ? " admin" : "")}>
              {user ? user.name[0].toUpperCase() : "?"}
            </span>
            <div className="session-text">
              <div className="session-name">{user ? user.name : t("session.signIn")}</div>
              <small>
                {user ? (isAdmin ? t("session.admin") : t("session.citizen")) : t("session.prompt")}
              </small>
            </div>
            {user && (
              <button
                className="icon-button"
                title={t("session.signOut")}
                aria-label={t("session.signOut")}
                onClick={(e) => {
                  e.stopPropagation();
                  handleLogout();
                }}
              >
                <X size={14} />
              </button>
            )}
          </div>
        </div>
      </aside>

      {/* MAIN CONTAINER */}
      <div className="main">
        {/* TOPBAR */}
        <header className="topbar">
          <button
            className="mobile-menu icon-button"
            onClick={() => setMobile(!mobile)}
            aria-label={t("top.toggleNav")}
          >
            <Menu />
          </button>

          <div className="breadcrumb">
            {t("top.workspace")} <ChevronRight size={14} />
            <strong>{t(`nav.${page}`)}</strong>
          </div>

          <div className="top-search search-box">
            <Search size={16} />
            <input
              aria-label={t("top.searchAll")}
              placeholder={t("top.searchPh")}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                if (page === "Report Issue") changePage("Overview");
              }}
            />
          </div>

          <div className="top-actions">
            {isAdmin && (
              <span className="role-chip">
                <ShieldCheck size={14} />
                {t("top.admin")}
              </span>
            )}

            <div
              className={"connection " + (connection === "Live" ? "online" : "")}
            >
              <span />
              {connection === "Live" ? t("top.live") : connection}
            </div>

            <div className="lang-switch" role="group" aria-label={t("lang.label")}>
              {(["en", "kn"] as const).map((l) => (
                <button
                  key={l}
                  type="button"
                  lang={l}
                  className={lang === l ? "active" : ""}
                  aria-pressed={lang === l}
                  onClick={() => setLang(l)}
                >
                  {l === "en" ? "EN" : t("lang.kn")}
                </button>
              ))}
            </div>

            {user ? (
              <button className="secondary" onClick={handleLogout}>
                {t("top.signOut")}
              </button>
            ) : (
              <button className="secondary" onClick={() => setAuthModal(true)}>
                {t("top.signIn")}
              </button>
            )}

            {!isNigam && (
              <button className="primary top-report" onClick={report} aria-label={t("top.report")}>
                <Plus size={17} />
                <span className="top-report-label">{t("top.report")}</span>
              </button>
            )}
          </div>
        </header>

        {/* MAIN BODY CONTENT */}
        <main>
          {page === "Report Issue" ? (
            <>
              <div className="page-heading">
                <h1>{t("report.title")}</h1>
                <p>{t("report.subtitle")}</p>
              </div>

              {success ? (
                <section className="success card">
                  <div className="success-icon">
                    <Check size={32} />
                  </div>
                  <h2>{t("success.title")}</h2>
                  <p>{t("success.body")}</p>
                  <div style={{ margin: "16px 0", fontSize: "16px" }}>
                    <strong>{success.public_reference || t("common.reportNo", { id: success.id })}</strong> ·{" "}
                    {t("success.status")}{" "}
                    <span className="status open">
                      <i /> {t("status.open")}
                    </span>
                  </div>
                  <div className="button-row">
                    <button className="primary" onClick={() => setSuccess(null)}>
                      {t("success.another")}
                    </button>
                    <button
                      className="secondary"
                      onClick={() => changePage("My Reports")}
                    >
                      {t("success.mine")}
                    </button>
                  </div>
                </section>
              ) : (
                <div className="report-layout">
                  <section className="report-card card">
                    <div className="steps">
                      {[t("steps.1"), t("steps.2"), t("steps.3")].map((x, i) => (
                        <div key={x} className={step >= i + 1 ? "current" : ""}>
                          <span>
                            {step > i + 1 ? <Check size={15} /> : i + 1}
                          </span>
                          {x}
                        </div>
                      ))}
                    </div>

                    {step === 1 ? (
                      <>
                        <div className="section-number">{t("steps.of", { n: 1 })}</div>
                        <h2>{t("s1.title")}</h2>
                        <p className="muted">{t("s1.sub")}</p>

                        <label className="field-label">
                          {t("s1.type")} <span>*</span>
                        </label>
                        <div className="issue-choices">
                          {[
                            { key: "electric_pole_fallen", icon: AlertTriangle },
                            { key: "pothole", icon: Construction },
                            { key: "waterlogging", icon: Droplets },
                            { key: "both", icon: MapPin },
                            { key: "garbage_accumulation", icon: Trash2 },
                            { key: "streetlight_failure", icon: ShieldCheck },
                          ].map(({ key, icon: Icon }) => ({
                            key,
                            icon: Icon,
                            label: t(`choice.${key}`),
                            desc: t(`choice.${key}.desc`),
                          })).map(({ key, label, desc, icon: Icon }) => (
                            <button
                              key={key}
                              type="button"
                              className={
                                "issue-choice " +
                                key +
                                (form.issue_type === key ? " chosen" : "")
                              }
                              onClick={() => {
                                const newSeriousness =
                                  key === "electric_pole_fallen"
                                    ? "critical_hazard"
                                    : form.seriousness;
                                const newAnalysis = null;
                                setForm({
                                  ...form,
                                  issue_type: key,
                                  seriousness: newSeriousness,
                                  analysis: newAnalysis,
                                });
                              }}
                            >
                              <Icon size={24} />
                              <strong>{label}</strong>
                              <small>{desc}</small>
                              {form.issue_type === key && (
                                <Check className="choice-check" size={17} />
                              )}
                            </button>
                          ))}
                        </div>

                        <label className="field-label">
                          {t("sev.label")} <span>*</span>
                        </label>
                        <div
                          style={{
                            display: "grid",
                            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                            gap: "8px",
                            marginBottom: "16px",
                          }}
                        >
                          {["critical_hazard", "standard", "minor"].map((id) => ({
                            id,
                            label: t(`sev.${id}`),
                            desc: t(`sev.${id}.desc`),
                          })).map((s) => (
                            <button
                              key={s.id}
                              type="button"
                              style={{
                                padding: "10px 12px",
                                textAlign: "left",
                                borderRadius: "8px",
                                border:
                                  form.seriousness === s.id
                                    ? "2px solid #2563eb"
                                    : "1px solid #cbd5e1",
                                background:
                                  form.seriousness === s.id ? "#eff6ff" : "#fff",
                                cursor: "pointer",
                              }}
                              onClick={() =>
                                setForm({
                                  ...form,
                                  seriousness: s.id as any,
                                })
                              }
                            >
                              <strong
                                style={{
                                  display: "block",
                                  fontSize: "13px",
                                  marginBottom: "2px",
                                }}
                              >
                                {s.label}
                              </strong>
                              <small
                                style={{
                                  display: "block",
                                  fontSize: "11px",
                                  color: "#64748b",
                                }}
                              >
                                {s.desc}
                              </small>
                            </button>
                          ))}
                        </div>

                        <label className="field-label" htmlFor="description">
                          {t("desc.label")} *
                        </label>
                        <textarea
                          id="description"
                          maxLength={500}
                          rows={6}
                          placeholder={t("desc.ph")}
                          value={form.description}
                          onChange={(e) => {
                            const val = e.target.value;
                            const lower = val.toLowerCase();
                            let detectedIssue = form.issue_type;
                            let detectedSeriousness = form.seriousness;

                            if (
                              lower.includes("electric pole") ||
                              lower.includes("live wire") ||
                              lower.includes("sparking") ||
                              val.includes("ವಿದ್ಯುತ್ ಕಂಬ") ||
                              val.includes("ವಿದ್ಯುತ್ ತಂತಿ")
                            ) {
                              detectedIssue = "electric_pole_fallen";
                              detectedSeriousness = "critical_hazard";
                            } else if (
                              lower.includes("small") ||
                              lower.includes("minor") ||
                              lower.includes("shallow") ||
                              val.includes("ಸಣ್ಣ")
                            ) {
                              detectedSeriousness = "minor";
                            }

                            setForm({
                              ...form,
                              description: val,
                              issue_type: detectedIssue,
                              seriousness: detectedSeriousness,
                            });
                          }}
                        />
                        <div className="field-foot">
                          <span>{t("desc.hint")}</span>
                          <span>{form.description.trim().length}/500</span>
                        </div>
                      </>
                    ) : step === 2 ? (
                      <>
                        <div className="section-number">{t("steps.of", { n: 2 })}</div>
                        <h2>{t("s2.title")}</h2>
                        <p className="muted">{t("s2.sub")}</p>

                        <input
                          ref={fileInput}
                          hidden
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          onChange={(e) =>
                            e.target.files?.[0] && chooseFile(e.target.files[0])
                          }
                        />

                        {preview ? (
                          <div className="photo-preview">
                            <img src={preview} alt={t("photo.alt")} />
                            <div className="button-row">
                              <button
                                type="button"
                                className="secondary"
                                onClick={() => fileInput.current?.click()}
                              >
                                {t("photo.replace")}
                              </button>
                              <button
                                type="button"
                                className="text-button"
                                onClick={() => setForm({ ...form, file: null, analysis: null })}
                              >
                                {t("photo.remove")}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="upload-zone"
                            onClick={() => fileInput.current?.click()}
                            onDragOver={(e) => e.preventDefault()}
                            onDrop={(e) => {
                              e.preventDefault();
                              if (e.dataTransfer.files?.[0]) {
                                chooseFile(e.dataTransfer.files[0]);
                              }
                            }}
                          >
                            <Upload size={28} />
                            <strong>{t("photo.upload")}</strong>
                            <span>{t("photo.types")}</span>
                          </button>
                        )}

                        {form.file && (
                          <p style={{ marginTop: "12px", fontSize: "12px", color: "var(--muted)" }}>
                            {t("photo.check")}
                          </p>
                        )}

                        <div className="location-heading">
                          <label className="field-label">{t("loc.label")} *</label>
                          <span className="muted">{t("loc.hint")}</span>
                        </div>

                        <div className="picker-map">
                          <ComplaintMap
                            point={
                              form.latitude === null || form.longitude === null
                                ? null
                                : [form.latitude, form.longitude]
                            }
                            onPoint={(p) =>
                              setForm((f) => ({
                                ...f,
                                latitude: p[0],
                                longitude: p[1],
                                confirmed: true,
                              }))
                            }
                          />
                        </div>

                        <div className="coordinates">
                          <label>
                            {t("loc.lat")}
                            <input
                              type="number"
                              step="any"
                              value={form.latitude ?? ""}
                              onChange={(e) =>
                                setForm({
                                  ...form,
                                  latitude: Number(e.target.value),
                                })
                              }
                            />
                          </label>
                          <label>
                            {t("loc.lng")}
                            <input
                              type="number"
                              step="any"
                              value={form.longitude ?? ""}
                              onChange={(e) =>
                                setForm({
                                  ...form,
                                  longitude: Number(e.target.value),
                                })
                              }
                            />
                          </label>
                        </div>

                        <label className="field-label" htmlFor="landmark">
                          {t("landmark.label")} <small>{t("landmark.optional")}</small>
                        </label>
                        <input
                          id="landmark"
                          maxLength={150}
                          value={form.landmark}
                          onChange={(e) =>
                            setForm({ ...form, landmark: e.target.value, landmarkEdited: true })
                          }
                          placeholder={landmarkLookup === "looking" && !form.landmark ? t("landmark.looking") : t("landmark.ph")}
                          aria-describedby="landmark-hint"
                        />
                        <div id="landmark-hint" className="landmark-hint" aria-live="polite">
                          {landmarkLookup === "looking" ? (
                            <span>
                              <LoaderCircle size={13} className="spin" /> {t("landmark.looking")}
                            </span>
                          ) : form.landmarkEdited ? (
                            suggestedLandmark &&
                            suggestedLandmark !== form.landmark && (
                              <button
                                type="button"
                                className="text-button"
                                onClick={() =>
                                  setForm((f) => ({ ...f, landmark: suggestedLandmark, landmarkEdited: false }))
                                }
                              >
                                <MapPin size={13} /> {t("landmark.useSuggestion", { name: suggestedLandmark })}
                              </button>
                            )
                          ) : landmarkLookup === "found" ? (
                            <span>
                              <MapPin size={13} /> {t("landmark.auto")}
                            </span>
                          ) : landmarkLookup === "failed" ? (
                            <span>{t("landmark.failed")}</span>
                          ) : null}
                        </div>

                        <label className="checkbox">
                          <input
                            type="checkbox"
                            checked={form.confirmed}
                            onChange={(e) =>
                              setForm({ ...form, confirmed: e.target.checked })
                            }
                          />
                          {t("loc.confirm")}
                        </label>
                      </>
                    ) : (
                      <>
                        <div className="section-number">{t("steps.of", { n: 3 })}</div>
                        <h2>{t("s3.title")}</h2>
                        <p className="muted">{t("s3.sub")}</p>

                        <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "12px" }}>
                          <span className={"badge " + form.issue_type}>
                            {issueName(form.issue_type)}
                          </span>
                          {form.seriousness === "critical_hazard" ? (
                            <span
                              style={{
                                background: "#fee2e2",
                                color: "#991b1b",
                                fontWeight: 700,
                                fontSize: "11px",
                                padding: "3px 8px",
                                borderRadius: "4px",
                                border: "1px solid #fca5a5",
                              }}
                            >
                              {t("sev.critical_hazard")}
                            </span>
                          ) : form.seriousness === "minor" ? (
                            <span
                              style={{
                                background: "#fef3c7",
                                color: "#92400e",
                                fontWeight: 700,
                                fontSize: "11px",
                                padding: "3px 8px",
                                borderRadius: "4px",
                                border: "1px solid #fde68a",
                              }}
                            >
                              {t("sev.minor")}
                            </span>
                          ) : (
                            <span
                              style={{
                                background: "#eff6ff",
                                color: "#1e40af",
                                fontWeight: 700,
                                fontSize: "11px",
                                padding: "3px 8px",
                                borderRadius: "4px",
                                border: "1px solid #bfdbfe",
                              }}
                            >
                              {t("sev.standard")}
                            </span>
                          )}
                          {form.analysis?.is_suspicious && (
                            <span
                              style={{
                                background: "#fffbeb",
                                color: "#b45309",
                                fontWeight: 700,
                                fontSize: "11px",
                                padding: "3px 8px",
                                borderRadius: "4px",
                                border: "1px solid #fde68a",
                              }}
                            >
                              {t("s3.suspicious")}
                            </span>
                          )}
                        </div>

                        <p className="review-description">{form.description}</p>

                        {preview && (
                          <div className="analysis-image">
                            <img src={preview} alt={t("s3.imgAlt")} />
                          </div>
                        )}

                        <p className="location-line">
                          <MapPin size={16} />
                          {form.latitude?.toFixed(6)}, {form.longitude?.toFixed(6)}
                          {form.landmark && " · " + form.landmark}
                        </p>

                        {/* LIVE PRIORITISATION PREVIEW */}
                        {(() => {
                          const live = calculatePriorityScore({
                            issue_type: form.issue_type,
                            claimed_category: form.issue_type,
                            description: form.description,
                            seriousness: form.seriousness,
                            latitude: form.latitude,
                            longitude: form.longitude,
                            duplicate_count: 0,
                            priority: form.issue_type === "electric_pole_fallen" ? "urgent" : "normal",
                          });

                          return (
                            <div
                              style={{
                                background: "#f8fafc",
                                border: "1px solid #cbd5e1",
                                borderRadius: "8px",
                                padding: "14px",
                                margin: "16px 0",
                              }}
                            >
                              <div
                                style={{
                                  display: "flex",
                                  justifyContent: "space-between",
                                  alignItems: "center",
                                  marginBottom: "8px",
                                }}
                              >
                                <strong style={{ fontSize: "13px", color: "#334155" }}>
                                  {t("s3.estimate")}
                                </strong>
                                <span
                                  className={"priority-pill " + live.band}
                                  style={{
                                    padding: "3px 8px",
                                    borderRadius: "4px",
                                    fontWeight: 700,
                                    fontSize: "12px",
                                    background:
                                      live.score >= 90
                                        ? "#fef2f2"
                                        : live.score >= 75
                                        ? "#fffbeb"
                                        : "#f0fdf4",
                                    color:
                                      live.score >= 90
                                        ? "#991b1b"
                                        : live.score >= 75
                                        ? "#92400e"
                                        : "#166534",
                                    border: `1px solid ${
                                      live.score >= 90
                                        ? "#fecaca"
                                        : live.score >= 75
                                        ? "#fde68a"
                                        : "#bbf7d0"
                                    }`,
                                  }}
                                >
                                  {live.score.toFixed(1)} / 100
                                </span>
                              </div>
                              <ul
                                style={{
                                  margin: 0,
                                  paddingLeft: "16px",
                                  fontSize: "12px",
                                  color: "#64748b",
                                }}
                              >
                                {live.reasons.map((r, i) => (
                                  <li key={i} style={{ marginBottom: "2px" }}>
                                    {r}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          );
                        })()}

                        <div className="privacy-note">
                          <Info size={18} />
                          <span>{t("s3.note")}</span>
                        </div>
                      </>
                    )}

                    {formError && (
                      <p className="error-box" role="alert">
                        {formError}
                      </p>
                    )}

                    <div className="form-footer">
                      <button
                        type="button"
                        className="text-button"
                        onClick={() =>
                          step === 1 ? changePage("Overview") : setStep(step - 1)
                        }
                      >
                        <ChevronLeft size={16} />
                        {step === 1 ? t("form.backOverview") : t("form.back")}
                      </button>

                      {step < 3 ? (
                        <button type="button" className="primary" onClick={nextStep}>
                          {t("form.continue")} <ArrowRight size={17} />
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="primary"
                          disabled={saving}
                          onClick={submitComplaint}
                        >
                          {saving ? (
                            <LoaderCircle size={17} className="spin" />
                          ) : (
                            <Plus size={17} />
                          )}{" "}
                          {saving ? t("form.submitting") : t("form.submit")}
                        </button>
                      )}
                    </div>
                  </section>

                  <aside className="report-help">
                    <div className="help-icon">
                      <ShieldCheck size={27} />
                    </div>
                    <h3>{t("help.title")}</h3>
                    <p>{t("help.body")}</p>
                    <div>
                      <Check size={16} />
                      {t("help.1")}
                    </div>
                    <div>
                      <Check size={16} />
                      {t("help.2")}
                    </div>
                    <div>
                      <Check size={16} />
                      {t("help.3")}
                    </div>
                    <hr />
                    <small>{t("help.foot")}</small>
                  </aside>
                </div>
              )}
            </>
          ) : (
            <>
              {/* PAGE HEADING */}
              <div className="page-heading">
                <div className="heading-row">
                  <h1>{t(`page.${page}.h`)}</h1>
                  <span className="region">
                    <MapPin size={15} /> {t("page.region")}
                  </span>
                </div>
                <p>{t(`page.${page}.p`)}</p>
              </div>

              {/* STAT METRIC CARDS */}
              {page === "Overview" && (
                <div className="ledger">
                  {statCards.map(([title, k, sub, filter], i) => {
                    const Icon = statIcons[i];
                    const active =
                      (issue === filter && filter && filter !== "resolved") ||
                      (filter === "resolved" && status === "resolved");
                    const value = metrics ? metrics[k] ?? total ?? 0 : total;
                    return (
                      <button
                        key={k}
                        className={"ledger-cell " + k + (active ? " active" : "")}
                        aria-pressed={!!active}
                        style={{ "--i": i } as React.CSSProperties}
                        onClick={() => {
                          // Clicking the active filter again clears it, like the stage buttons.
                          const next = active ? "" : filter;
                          setIssue(next === "resolved" ? "" : next);
                          setStatus(next === "resolved" ? "resolved" : "");
                        }}
                      >
                        <span className="ledger-label">
                          <Icon size={16} />
                          {title}
                        </span>
                        <strong className="ledger-value">
                          {value === null ? "…" : <CountUp value={value} />}
                        </strong>
                        <small>{metrics ? sub : t("stat.active")}</small>
                        <span className="lane-dash" aria-hidden="true" />
                      </button>
                    );
                  })}
                </div>
              )}

              {/* MAIN WORKSPACE SECTION */}
              <section className="card workspace">
                <div className={"road-progress" + (busy ? " on" : "")} aria-hidden="true" />
                <div className="workspace-header">
                  <div>
                    <div className="panel-title">
                      <span className="section-icon">
                        <MapIcon size={19} />
                      </span>
                      <h2>{page === "My Reports" ? t("ws.mine") : t("ws.neighbourhood")}</h2>
                      {user && (
                        <span className="outline-badge">
                          {total === null
                            ? t("ws.loading")
                            : t(total === 1 ? "ws.count.one" : "ws.count.many", { n: total })}
                        </span>
                      )}
                    </div>
                    <p>
                      {!user || total === null
                        ? t("ws.blurb")
                        : t("ws.showing", { shown: rows.length, total })}
                    </p>
                  </div>
                  <button
                    className="text-button refresh"
                    onClick={reload}
                    disabled={busy}
                  >
                    <RefreshCw size={15} className={busy ? "spin" : ""} />
                    {t("ws.refresh")}
                  </button>
                </div>

                {/* FILTER BAR */}
                <div className="filter-bar">
                  <div className="search-box">
                    <Search size={17} />
                    <input
                      aria-label={t("filter.searchAria")}
                      placeholder={t("filter.searchPh")}
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                    {search && (
                      <button
                        className="icon-button"
                        onClick={() => setSearch("")}
                        aria-label={t("filter.clearSearch")}
                      >
                        <X size={14} />
                      </button>
                    )}
                  </div>

                  <select
                    aria-label={t("filter.issueAria")}
                    value={issue}
                    onChange={(e) => setIssue(e.target.value)}
                  >
                    <option value="">{t("filter.allIssues")}</option>
                    {Object.keys(issueLabels).map((k) => (
                      <option value={k} key={k}>
                        {issueName(k)}
                      </option>
                    ))}
                  </select>

                  <select
                    aria-label={t("filter.statusAria")}
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                  >
                    <option value="">{t("filter.allStatuses")}</option>
                    {Object.keys(statusLabels).map((k) => (
                      <option value={k} key={k}>
                        {statusName(k)}
                      </option>
                    ))}
                  </select>

                  <input
                    className="date-filter"
                    type="date"
                    title={t("filter.from")}
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                  />

                  <input
                    className="date-filter"
                    type="date"
                    title={t("filter.through")}
                    value={until}
                    min={date}
                    onChange={(e) => setUntil(e.target.value)}
                  />

                  {filterActive && (
                    <button className="text-button" onClick={clearFilters}>
                      {t("filter.clear")}
                    </button>
                  )}
                </div>

                {/* MOBILE VIEW SWITCH */}
                <div className="mobile-switch">
                  <button
                    className={view === "map" ? "active" : ""}
                    onClick={() => setView("map")}
                  >
                    <MapIcon size={16} />
                    {t("view.map")}
                  </button>
                  <button
                    className={view === "list" ? "active" : ""}
                    onClick={() => setView("list")}
                  >
                    <FileText size={16} />
                    {t("view.list")}
                  </button>
                </div>

                {error && (
                  <div className="error-box" role="alert">
                    {error}
                    <button className="text-button" onClick={reload}>
                      {t("common.retry")}
                    </button>
                  </div>
                )}

                {/* MAP & COMPLAINT LIST SPLIT VIEW */}
                <div className={"map-list view-" + view}>
                  <div className="main-map">
                    <ComplaintMap
                      rows={rows}
                      selected={selected}
                      onSelect={setSelected}
                      onDetails={openDetails}
                    />
                    <div className="map-caption">
                      <span>
                        <span className="dot live" />
                        {t("map.caption")}
                      </span>
                      <small>{t("map.privacy")}</small>
                    </div>
                  </div>

                  <div className="complaint-list" id="complaints">
                    <div className="list-heading">
                      <h3>{page === "My Reports" ? t("list.mine") : t("list.recent")}</h3>
                      <select
                        aria-label={t("list.sortAria")}
                        value={sort}
                        onChange={(e) => setSort(e.target.value)}
                      >
                        <option value="priority">{t("list.sortPriority")}</option>
                        <option value="newest">{t("list.sortNewest")}</option>
                        <option value="oldest">{t("list.sortOldest")}</option>
                      </select>
                    </div>

                    {!user ? (
                      <div className="list-empty">
                        <span className="empty-art">
                          <ShieldCheck size={30} />
                        </span>
                        <p>{t("list.signInPrompt")}</p>
                        <button className="primary" onClick={() => setAuthModal(true)}>
                          {t("session.signIn")}
                        </button>
                      </div>
                    ) : busy ? (
                      <div className="skeletons">
                        {[1, 2, 3].map((x) => (
                          <div className="skeleton" key={x} />
                        ))}
                      </div>
                    ) : rows.length ? (
                      rows.map((r, i) => {
                        const score: number | undefined = r.priority_score;
                        const band = score === undefined ? "" : score >= 90 ? "critical" : score >= 75 ? "elevated" : "routine";
                        return (
                          <button
                            key={r.id}
                            className={"complaint-row " + band + (selected?.id === r.id ? " selected" : "")}
                            style={{ "--i": Math.min(i, 12) } as React.CSSProperties}
                            onClick={() => {
                              setSelected(r);
                              openDetails(r);
                            }}
                          >
                            <div className="complaint-row-top">
                              <span className={"badge " + r.issue_type}>
                                {issueName(r.issue_type)}
                              </span>
                              <small>{new Date(r.created_at).toLocaleDateString(locale)}</small>
                            </div>
                            <h4>{r.description}</h4>
                            <span className="reference">
                              {r.public_reference || t("common.reportNo", { id: r.id.slice(0, 8) })}
                            </span>

                            {(score !== undefined || r.duplicate_count > 0 || r.is_suspicious) && (
                              <div className="row-flags">
                                {score !== undefined && (
                                  <span
                                    className={"priority-meter " + band}
                                    title={r.priority_reason || t("list.scoreTitle", { score: score.toFixed(1) })}
                                  >
                                    <span className="meter-track">
                                      <span style={{ width: `${Math.min(100, score)}%` }} />
                                    </span>
                                    {score.toFixed(0)}
                                  </span>
                                )}
                                {r.duplicate_count > 0 && (
                                  <span className="flag duplicate">
                                    {t(r.duplicate_count === 1 ? "list.dup.one" : "list.dup.many", { n: r.duplicate_count })}
                                  </span>
                                )}
                                {r.is_suspicious && (
                                  <span className="flag suspicious">
                                    <AlertTriangle size={12} /> {t("list.suspicious")}
                                  </span>
                                )}
                              </div>
                            )}

                            {isAdmin && r.duplicate_count > 0 && (
                              <div className="row-admin" onClick={(e) => e.stopPropagation()}>
                                <button
                                  type="button"
                                  className="danger-ghost"
                                  onClick={() => triggerDeduplicateForReport(r)}
                                >
                                  <Trash2 size={13} />
                                  {t(r.duplicate_count === 1 ? "list.deleteDup.one" : "list.deleteDup.many", {
                                    n: r.duplicate_count,
                                  })}
                                </button>
                              </div>
                            )}

                            <div className="complaint-row-bottom">
                              <span className={"status " + (r.status || "open")}>
                                <i />
                                {statusName(r.status || "open")}
                              </span>
                              <ArrowUpRight size={16} />
                            </div>
                          </button>
                        );
                      })
                    ) : (
                      <div className="list-empty">
                        <span className="empty-art">
                          <MapPin size={31} />
                          <span className="empty-check">
                            <Check size={12} />
                          </span>
                        </span>
                        <p>
                          {filterActive
                            ? t("list.noMatch")
                            : page === "My Reports"
                            ? t("list.noneMine")
                            : t("list.none")}
                        </p>
                        {filterActive && (
                          <button className="secondary" onClick={clearFilters}>
                            {t("filter.clear")}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </section>

              {/* BOTTOM STATUS METRICS GRID */}
              {page === "Overview" && (
                <div className="bottom-grid">
                  <section className="card status-card">
                    <div className="panel-title">
                      <Clock size={18} />
                      <h3>{t("stages.title")}</h3>
                    </div>
                    <p>{t("stages.sub")}</p>
                    {(() => {
                      const sum = stages.reduce((n, k) => n + (metrics?.[k] ?? 0), 0);
                      return (
                        <>
                          <div className="lane-bar" aria-hidden="true">
                            {stages.map((k, i) => (
                              <span
                                key={k}
                                className={k}
                                style={{
                                  flexGrow: sum ? metrics?.[k] ?? 0 : 1,
                                  "--i": i,
                                } as React.CSSProperties}
                              />
                            ))}
                          </div>
                          <div className="status-items">
                            {stages.map((k) => (
                              <button
                                key={k}
                                className={status === k ? "active" : ""}
                                aria-pressed={status === k}
                                onClick={() => setStatus(status === k ? "" : k)}
                              >
                                <span className={"status " + k}>
                                  <i />
                                  {statusName(k)}
                                </span>
                                <strong>{metrics ? <CountUp value={metrics[k] ?? 0} /> : "—"}</strong>
                              </button>
                            ))}
                          </div>
                        </>
                      );
                    })()}
                  </section>

                  <section className="community-card">
                    <span className="community-icon">
                      <Construction size={28} />
                    </span>
                    <div>
                      <h3>{isAdmin ? t("community.adminTitle") : t("community.title")}</h3>
                      <p>{isAdmin ? t("community.adminBody") : t("community.body")}</p>
                      <button className="text-button" onClick={report}>
                        {isAdmin ? t("community.adminCta") : t("community.cta")}{" "}
                        <ArrowRight size={16} />
                      </button>
                    </div>
                  </section>
                </div>
              )}

              {/* FOOTER */}
              <footer>
                <span>
                  <span className="footer-brand">NagarSaathi</span> {t("footer.built")}
                </span>
                <span>{t("footer.pilot")}</span>
              </footer>
            </>
          )}
        </main>
      </div>

      {/* TOAST ALERT */}
      {toast && (
        <div className="toast" role="status" key={toast}>
          <Check size={17} />
          {toast}
        </div>
      )}

      {/* COMPLAINT DETAILS DRAWER */}
      {detail && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => e.target === e.currentTarget && closeDetails()}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="dialog-title"
            className="details-drawer"
          >
            <button
              ref={closeRef}
              className="close icon-button"
              onClick={closeDetails}
              aria-label={t("drawer.close")}
            >
              <X />
            </button>

            <div className="drawer-kicker">{t("drawer.kicker")}</div>
            <h2 id="dialog-title">
              {detail.public_reference || t("common.reportNo", { id: detail.id.slice(0, 8) })}
            </h2>

            {/* Suspicious Mismatch Warning Alert */}
            {detail.is_suspicious && (
              <div className="drawer-alert" role="note">
                <AlertTriangle size={20} />
                <div>
                  <strong>{t("drawer.suspicious")}</strong>
                  <span>{detail.suspicious_reason || t("drawer.suspiciousDefault")}</span>
                </div>
              </div>
            )}

            <div className="button-row">
              <span className={"badge " + detail.issue_type}>
                {issueName(detail.issue_type)}
              </span>
              <span className={"status " + (detail.status || "open")}>
                <i />
                {statusName(detail.status || "open")}
              </span>
            </div>

            <p className="review-description">{detail.description}</p>

            {detail.photo_url && (
              <AuthImage
                className="detail-photo"
                src={reportPhotoUrl(detail.photo_url)}
                alt={t("drawer.evidence")}
              />
            )}

            {detail.latitude && detail.longitude && (
              <p className="location-line">
                <MapPin size={17} />
                {Number(detail.latitude).toFixed(6)}, {Number(detail.longitude).toFixed(6)}
              </p>
            )}

            <dl>
              <dt>{t("drawer.submitted")}</dt>
              <dd>{new Date(detail.created_at).toLocaleString(locale)}</dd>
            </dl>

            {/* PRIORITY BREAKDOWN */}
            {(() => {
              const pe = calculatePriorityScore(detail);
              const band = pe.score >= 90 ? "critical" : pe.score >= 75 ? "elevated" : "routine";
              return (
                <section className="drawer-panel">
                  <div className="drawer-panel-head">
                    <h3>{t("drawer.priority")}</h3>
                    <span className={"score-chip " + band}>{pe.score.toFixed(1)} / 100</span>
                  </div>
                  <ul className="reason-list">
                    {pe.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </section>
              );
            })()}

            {/* ADMIN ONLY CONTROLS */}
            {isAdmin && (
              <>
                <section className="drawer-panel">
                  <div className="drawer-panel-head">
                    <h3>
                      <ShieldCheck size={17} /> {t("drawer.review")}
                    </h3>
                  </div>
                  <div className="field-grid">
                    <label>
                      {t("drawer.status")}
                      <select
                        value={reviewForm.status}
                        onChange={(e) => setReviewForm({ ...reviewForm, status: e.target.value })}
                      >
                        {/* Accepted reports move through their issue's stages; others stay in review states. */}
                        {(acceptedStatuses.includes(detail.status) ? acceptedStatuses : reviewStatuses).map((s) => (
                          <option key={s} value={s}>
                            {statusName(s)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      {t("drawer.priorityField")}
                      <select
                        value={reviewForm.priority}
                        onChange={(e) => setReviewForm({ ...reviewForm, priority: e.target.value })}
                      >
                        {["low", "normal", "high", "urgent"].map((p) => (
                          <option key={p} value={p}>
                            {t(`priority.${p}`)}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <label className="field-full">
                    {t("drawer.note")}
                    <input
                      type="text"
                      placeholder={t("drawer.notePh")}
                      value={reviewForm.priority_reason}
                      onChange={(e) => setReviewForm({ ...reviewForm, priority_reason: e.target.value })}
                    />
                  </label>
                  <div className="drawer-actions">
                    <button className="primary" disabled={reviewSaving} onClick={handleSaveReview}>
                      {reviewSaving ? t("drawer.saving") : t("drawer.save")}
                    </button>
                    <button className="danger-ghost" onClick={() => setDeleteModal(true)}>
                      <Trash2 size={15} /> {t("drawer.delete")}
                    </button>
                  </div>
                </section>

                {detail.duplicate_count > 0 && (
                  <section className="drawer-panel">
                    <div className="drawer-panel-head">
                      <h3>{t("drawer.duplicates")}</h3>
                    </div>
                    <p>
                      {t(detail.duplicate_count === 1 ? "drawer.dup.one" : "drawer.dup.many", {
                        n: detail.duplicate_count,
                      })}
                    </p>
                    <button type="button" className="danger-ghost" onClick={handleDeduplicateKeepOne}>
                      <Trash2 size={15} />{" "}
                      {t(detail.duplicate_count === 1 ? "list.deleteDup.one" : "list.deleteDup.many", {
                        n: detail.duplicate_count,
                      })}
                    </button>
                  </section>
                )}
              </>
            )}

            <div className="detail-actions">
              <button
                className="primary"
                onClick={() => {
                  changePage("Complaint Map");
                  setSelected(detail);
                  closeDetails();
                }}
              >
                <MapIcon size={16} />
                {t("drawer.showMap")}
              </button>

              <button
                className="secondary"
                onClick={() =>
                  navigator.clipboard
                    .writeText(String(detail.public_reference || detail.id))
                    .then(() => notify(t("toast.copied")))
                    .catch(() => notify(t("toast.noClipboard")))
                }
              >
                <Copy size={16} />
                {t("drawer.copy")}
              </button>
            </div>
          </section>
        </div>
      )}

      {/* SOFT DELETE REASON MODAL */}
      {deleteModal && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => e.target === e.currentTarget && setDeleteModal(false)}
        >
          <section
            role="dialog"
            aria-modal="true"
            className="details-drawer"
            style={{ maxWidth: "420px" }}
          >
            <button
              className="close icon-button"
              onClick={() => setDeleteModal(false)}
            >
              <X />
            </button>
            <div className="drawer-kicker">{t("del.kicker")}</div>
            <h2>{t("del.title")}</h2>
            <p style={{ color: "var(--muted)", fontSize: "13px", marginBottom: "14px" }}>
              {t("del.body")}
            </p>
            <label style={{ display: "block", marginBottom: "12px" }}>
              {t("del.reason")}
              <textarea
                rows={3}
                placeholder={t("del.reasonPh")}
                value={deleteReason}
                onChange={(e) => setDeleteReason(e.target.value)}
                style={{ width: "100%", marginTop: "6px" }}
              />
            </label>
            <div className="button-row" style={{ justifyContent: "flex-end", gap: "8px" }}>
              <button className="secondary" onClick={() => setDeleteModal(false)}>
                {t("del.cancel")}
              </button>
              <button
                className="primary"
                style={{ background: "#dc2626", borderColor: "#dc2626" }}
                disabled={deleteBusy || deleteReason.trim().length < 3}
                onClick={handleSoftDelete}
              >
                {deleteBusy ? t("del.deleting") : t("del.confirm")}
              </button>
            </div>
          </section>
        </div>
      )}

      {/* AUTHENTICATION MODAL */}
      {authModal && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => e.target === e.currentTarget && setAuthModal(false)}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="auth-title"
            className="details-drawer"
            style={{ maxWidth: "440px" }}
          >
            <button
              className="close icon-button"
              onClick={() => setAuthModal(false)}
              aria-label={t("drawer.close")}
            >
              <X />
            </button>

            <div className="drawer-kicker">{t("auth.kicker")}</div>
            <h2 id="auth-title">{t("auth.title")}</h2>
            <p style={{ fontSize: "13px", color: "var(--muted)", marginBottom: "16px" }}>
              {t("auth.body")}
              {authOptions.demo_enabled ? t("auth.demoAvailable") : ""}
            </p>

            <div style={{ display: "flex", borderBottom: "1px solid #e2e8f0", marginBottom: "20px" }}>
              {authOptions.demo_enabled && <button
                type="button"
                className="text-button"
                style={{
                  flex: 1,
                  padding: "10px",
                  borderBottom: authTab === "demo" ? "2px solid #087e72" : "none",
                  fontWeight: authTab === "demo" ? 700 : 500,
                  color: authTab === "demo" ? "#087e72" : "#64748b",
                }}
                onClick={() => setAuthTab("demo")}
              >
                {t("auth.demoTab")}
              </button>}
              <button
                type="button"
                className="text-button"
                style={{
                  flex: 1,
                  padding: "10px",
                  borderBottom: authTab === "login" ? "2px solid #087e72" : "none",
                  fontWeight: authTab === "login" ? 700 : 500,
                  color: authTab === "login" ? "#087e72" : "#64748b",
                }}
                onClick={() => setAuthTab("login")}
              >
                {t("auth.googleTab")}
              </button>
            </div>

            {authError && (
              <div className="error-box" style={{ margin: "0 0 16px 0" }}>
                {authError}
              </div>
            )}

            {authTab === "demo" && authOptions.demo_enabled ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <p style={{ fontSize: "12px", color: "var(--muted)", margin: 0 }}>
                  {t("auth.demoIntro")}
                </p>

                <button
                  type="button"
                  className="primary"
                  style={{
                    background: "#b45309",
                    borderColor: "#b45309",
                    justifyContent: "center",
                    padding: "12px",
                  }}
                  disabled={authLoading}
                  onClick={() => handleDemoLogin("admin")}
                >
                  <ShieldCheck size={18} />
                  <span>{t("auth.demoAdmin")}</span>
                </button>

                <button
                  type="button"
                  className="secondary"
                  style={{
                    justifyContent: "center",
                    padding: "12px",
                    fontWeight: 600,
                  }}
                  disabled={authLoading}
                  onClick={() => handleDemoLogin("citizen")}
                >
                  <span>{t("auth.demoCitizen")}</span>
                </button>
              </div>
            ) : (
              <div>
                <p style={{ fontSize: "12px", color: "var(--muted)", marginBottom: "14px" }}>
                  {t("auth.googleIntro")}
                </p>

                {/* Google Identity Services official button container */}
                <div
                  id="gsi-button-slot"
                  style={{
                    display: "flex",
                    justifyContent: "center",
                    minHeight: "44px",
                    marginBottom: "16px",
                  }}
                />

                {!authOptions.google_client_id && (
                  <div className="error-box" style={{ margin: 0 }}>
                    {t("auth.googleMissing")}
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
