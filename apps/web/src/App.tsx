import React, { useState, useEffect, useRef } from "react";
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
import "./style.css";

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
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
  rejected: "Rejected",
  submitted: "Submitted",
  awaiting_review: "Under review",
  out_of_scope: "Out of scope",
};

const nav: [string, any][] = [
  ["Overview", LayoutDashboard],
  ["Report Issue", Plus],
  ["Complaint Map", MapIcon],
  ["My Reports", FileText],
];

const fresh = () => ({
  issue_type: "pothole",
  seriousness: "standard" as "critical_hazard" | "standard" | "minor",
  description: "",
  file: null as File | null,
  latitude: 12.9172,
  longitude: 77.6228,
  landmark: "",
  confirmed: true,
  analysis: null as YoloAnalysisResult | null,
  forceMismatch: false,
});

/** Photos need the bearer token, which a plain <img src> cannot send: fetch and show a blob. */
function AuthImage({ src, alt, className }: { src: string; alt: string; className?: string }) {
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
  if (failed) return <p className="location-line">Photo could not be loaded.</p>;
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
    resolved: issues.resolved ?? 0,
    open: (reports.admitted ?? 0) + (reports.pending ?? 0),
    in_progress: issues.active ?? 0,
    rejected: reports.rejected ?? 0,
    suspicious: reports.suspicious ?? 0,
  };
}

export function App() {
  const [page, setPage] = useState<string>("Overview");
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

  const fileInput = useRef<HTMLInputElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const reload = () => setRefresh((x) => x + 1);

  const changePage = (p: string) => {
    setPage(p);
    setMobile(false);
    setOffset(0);
  };

  const report = () => changePage(isNigam ? "Overview" : "Report Issue");

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
      Promise.all([
        request(`/api/v1/complaints?${params.toString()}`),
        request("/api/v1/metrics").catch(() => null),
      ])
        .then(([data, m]) => {
          if (active) {
            setRows(data.items || []);
            setTotal(data.total ?? 0);
            if (m) setMetrics(flattenMetrics(m));
            setError("");
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        })
        .finally(() => {
          if (active) setBusy(false);
        });
    }, 150);

    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [search, issue, status, date, until, sort, page, offset, refresh, user]);

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
      notify(`Signed in as ${res.user.name} (${res.user.role.toUpperCase()})`);
      reload();
    } catch (err: any) {
      setAuthError(err.message || "Demo login failed");
    } finally {
      setAuthLoading(false);
    }
  }

  // Google Identity Services (GSI) API integration
  useEffect(() => {
    if (authModal && authTab === "login" && authOptions.google_client_id) {
      const initGsi = () => {
        const gsi = (window as any).google?.accounts?.id;
        if (gsi) {
          try {
            gsi.initialize({
              client_id: authOptions.google_client_id,
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
              });
            }
          } catch (e) {
            console.warn("GSI init info:", e);
          }
        }
      };
      const t = setTimeout(initGsi, 120);
      return () => clearTimeout(t);
    }
  }, [authModal, authTab, authOptions.google_client_id]);

  async function handleGoogleCredentialResponse(response: any) {
    if (!response?.credential) return;
    setAuthError("");
    setAuthLoading(true);
    try {
      const res = await loginWithGoogle({ credential: response.credential });
      setUser(res.user);
      setAuthModal(false);
      notify(`Signed in with Google as ${res.user.name}`);
      reload();
    } catch (err: any) {
      setAuthError(err.message || "Google Sign-In failed");
    } finally {
      setAuthLoading(false);
    }
  }

  // Admin Direct Duplicate Cleanup from List
  async function triggerDeduplicateForReport(report: any) {
    if (
      !window.confirm(
        `Are you sure you want to delete all other duplicate complaints associated with this incident and keep only #${report.public_reference || report.id.slice(0, 8)}?`
      )
    ) {
      return;
    }
    try {
      const res = await deduplicateKeepOne(report.id);
      notify(res.message || "Duplicates deleted successfully");
      reload();
    } catch (e: any) {
      notify(`Deduplication failed: ${e.message}`);
    }
  }

  // Logout Handler
  async function handleLogout() {
    await logout();
    setUser(null);
    setDetail(null);
    notify("Signed out");
    reload();
  }

  // File selection
  function chooseFile(file: File) {
    if (file.size > 15 * 1024 * 1024) {
      setFormError("Photo exceeds maximum limit of 15MB");
      return;
    }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setFormError("Please select a valid image (JPEG, PNG, or WebP)");
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
        setFormError("Please describe the civic issue (at least 5 characters).");
        return;
      }
      setFormError("");
      setStep(2);
    } else if (step === 2) {
      if (!form.file) {
        setFormError("Please upload a photo of the civic issue.");
        return;
      }
      if (!form.latitude || !form.longitude) {
        setFormError("Please mark the location on the map.");
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
      notify("Please sign in before submitting a complaint.");
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
          address_text: form.landmark || undefined,
        }),
      });

      setSuccess(reportRes);
      notify("Complaint successfully submitted to Bengaluru Pilot queue!");
      setForm(fresh());
      setStep(1);
      reload();
    } catch (err: any) {
      setFormError(err.message || "Failed to submit complaint");
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
      setDetail(updated);
      notify("Review updated successfully");
      reload();
    } catch (e: any) {
      notify(`Review failed: ${e.message}`);
    } finally {
      setReviewSaving(false);
    }
  }

  // Admin Soft Delete
  async function handleSoftDelete() {
    if (!detail) return;
    if (!deleteReason.trim()) {
      notify("Deletion reason is mandatory for moderation audit");
      return;
    }
    setDeleteBusy(true);
    try {
      await request(`/api/v1/reports/${detail.id}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: deleteReason }),
      });
      notify("Complaint soft-deleted. Audit event recorded.");
      setDeleteModal(false);
      setDeleteReason("");
      setDetail(null);
      reload();
    } catch (e: any) {
      notify(`Soft delete failed: ${e.message}`);
    } finally {
      setDeleteBusy(false);
    }
  }

  // Admin Deduplicate: Keep 1 & Delete All Duplicates
  async function handleDeduplicateKeepOne() {
    if (!detail) return;
    if (
      !window.confirm(
        `Are you sure you want to delete all other duplicate complaints associated with this issue and keep only Report #${detail.id}?`
      )
    ) {
      return;
    }

    try {
      const res = await deduplicateKeepOne(detail.id);
      notify(res.message || "Duplicates deleted successfully");
      const updated = await request(`/api/v1/complaints/${detail.id}`);
      setDetail(updated);
      reload();
    } catch (e: any) {
      notify(`Deduplication failed: ${e.message}`);
    }
  }

  const openDetails = (r: any) => {
    setDetail(r);
  };

  const closeDetails = () => {
    setDetail(null);
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
    [isAdmin ? "Consolidated issues" : "Total reports", "total", "Individual submissions", ""],
    ["Pothole reports", "pothole", "Road surface issues", "pothole"],
    ["Waterlogging reports", "waterlogging", "Drainage & flooding", "waterlogging"],
    ["Resolved reports", "resolved", "Issues verified resolved", "resolved"],
  ];

  return (
    <div className="app">
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
            NAGARSAATHI<small>YOUR CITY. OUR RESPONSIBILITY.</small>
          </span>
        </a>

        <div
          className="workspace-label"
          style={isAdmin ? { color: "#d97706", fontWeight: 700 } : undefined}
        >
          {isAdmin
            ? "PLATFORM ADMIN WORKSPACE"
            : isNigam
            ? "NAGAR NIGAM WORKSPACE"
            : "CITIZEN WORKSPACE"}
        </div>

        <nav>
          {nav.map(([p, Icon]) => (
            <button
              key={p}
              className={"nav-item " + (page === p ? "active" : "")}
              onClick={() => changePage(p)}
            >
              <Icon size={19} />
              {p}
              {page === p && <span className="active-dot" />}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="together">
            <span className="mini-icon">
              <ShieldCheck size={22} />
            </span>
            <h3>
              Small reports.
              <br />
              Better neighbourhoods.
            </h3>
            <p>
              Be the eyes of your city. Every issue you report is a step forward.
            </p>
            <button onClick={report}>
              {isAdmin ? "View all complaints" : "Make a difference"}{" "}
              <ArrowRight size={15} />
            </button>
          </div>

          <div
            className="session"
            onClick={() => (!user ? setAuthModal(true) : null)}
            style={{ cursor: user ? "default" : "pointer" }}
          >
            <span
              className="avatar"
              style={
                isAdmin
                  ? { background: "#d97706", color: "#fff" }
                  : undefined
              }
            >
              {user ? user.name[0].toUpperCase() : "C"}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontWeight: 600,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {user ? user.name : "Sign In / Register"}
              </div>
              <small style={{ display: "block" }}>
                {user
                  ? isAdmin
                    ? "Platform Administrator"
                    : "Citizen Account"
                  : "Click to Authenticate"}
              </small>
            </div>
            {user ? (
              <button
                className="icon-button"
                title="Sign out"
                onClick={(e) => {
                  e.stopPropagation();
                  handleLogout();
                }}
                style={{ padding: "4px" }}
              >
                <X size={14} />
              </button>
            ) : (
              <span className="session-dot" style={{ background: "#f59e0b" }} />
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
            aria-label="Toggle navigation"
          >
            <Menu />
          </button>

          <div className="breadcrumb">
            Workspace <ChevronRight size={14} />
            <strong>{page}</strong>
          </div>

          <div className="top-search search-box">
            <Search size={16} />
            <input
              aria-label="Search all complaints"
              placeholder="Search complaints…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                if (page === "Report Issue") changePage("Overview");
              }}
            />
          </div>

          <div className="top-actions">
            {isAdmin && (
              <span
                className="badge"
                style={{
                  background: "#fef3c7",
                  color: "#92400e",
                  fontWeight: 700,
                  padding: "6px 12px",
                  borderRadius: "6px",
                  fontSize: "12px",
                }}
              >
                🛡️ ADMIN
              </span>
            )}

            <div
              className={"connection " + (connection === "Live" ? "online" : "")}
            >
              <span />
              {connection}
            </div>

            {user ? (
              <button
                className="secondary"
                onClick={handleLogout}
                style={{ padding: "8px 14px", fontSize: "13px" }}
              >
                Sign Out
              </button>
            ) : (
              <button
                className="secondary"
                onClick={() => setAuthModal(true)}
                style={{ padding: "8px 14px", fontSize: "13px" }}
              >
                Sign In
              </button>
            )}

            {!isNigam && (
              <button className="primary" onClick={report}>
                <Plus size={17} />
                Report Issue
              </button>
            )}
          </div>
        </header>

        {/* MAIN BODY CONTENT */}
        <main>
          {page === "Report Issue" ? (
            <>
              <div className="page-heading">
                <div className="eyebrow">MAKE YOUR NEIGHBOURHOOD BETTER</div>
                <h1>Report an issue</h1>
                <p>A photo, a pin, and a few details can make a difference.</p>
              </div>

              {success ? (
                <section className="success card">
                  <div className="success-icon">
                    <Check size={32} />
                  </div>
                  <h2>Thank you for speaking up.</h2>
                  <p>Your complaint has been permanently saved to the database.</p>
                  <div style={{ margin: "16px 0", fontSize: "16px" }}>
                    <strong>{success.public_reference || `Report #${success.id}`}</strong> ·
                    Status:{" "}
                    <span className="status open">
                      <i /> Open
                    </span>
                  </div>
                  <div className="button-row">
                    <button className="primary" onClick={() => setSuccess(null)}>
                      Submit Another Report
                    </button>
                    <button
                      className="secondary"
                      onClick={() => changePage("My Reports")}
                    >
                      View My Reports
                    </button>
                  </div>
                </section>
              ) : (
                <div className="report-layout">
                  <section className="report-card card">
                    <div className="steps">
                      {[
                        "Issue details",
                        "Photo & location",
                        "Review & submit",
                      ].map((x, i) => (
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
                        <div className="section-number">STEP 01</div>
                        <h2>What needs attention?</h2>
                        <p className="muted">
                          Choose the issue you noticed and tell us a little more.
                        </p>

                        <label className="field-label">
                          Issue type <span>*</span>
                        </label>
                        <div className="issue-choices">
                          {[
                            { key: "electric_pole_fallen", label: "Electric Pole Fallen", desc: "Exposed wires / fallen pole hazard", icon: AlertTriangle },
                            { key: "pothole", label: "Pothole", desc: "Damaged road surface", icon: Construction },
                            { key: "waterlogging", label: "Waterlogging", desc: "Standing or flooding water", icon: Droplets },
                            { key: "both", label: "Both Issues", desc: "Pothole and waterlogging", icon: MapPin },
                            { key: "garbage_accumulation", label: "Garbage Pile", desc: "Waste accumulation on road", icon: Trash2 },
                            { key: "streetlight_failure", label: "Streetlight Failure", desc: "Dark road / broken light", icon: ShieldCheck },
                          ].map(({ key, label, desc, icon: Icon }) => (
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
                          Seriousness & Hazard Level <span>*</span>
                        </label>
                        <div
                          style={{
                            display: "grid",
                            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                            gap: "8px",
                            marginBottom: "16px",
                          }}
                        >
                          {[
                            {
                              id: "critical_hazard",
                              label: "🚨 Critical Hazard (95 pts)",
                              desc: "Fallen electric pole, live wires, or active road collapse",
                            },
                            {
                              id: "standard",
                              label: "⚠️ Standard Defect (65 pts)",
                              desc: "Deep road crater, large pothole, transit waterlogging",
                            },
                            {
                              id: "minor",
                              label: "🟡 Minor / Small Defect (40 pts)",
                              desc: "Small shallow pothole or minor residential surface wear",
                            },
                          ].map((s) => (
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
                          Description *
                        </label>
                        <textarea
                          id="description"
                          maxLength={500}
                          rows={6}
                          placeholder="What did you notice? Include details that will help municipal staff understand the issue."
                          value={form.description}
                          onChange={(e) => {
                            const val = e.target.value;
                            const lower = val.toLowerCase();
                            let detectedIssue = form.issue_type;
                            let detectedSeriousness = form.seriousness;

                            if (
                              lower.includes("electric pole") ||
                              lower.includes("live wire") ||
                              lower.includes("sparking")
                            ) {
                              detectedIssue = "electric_pole_fallen";
                              detectedSeriousness = "critical_hazard";
                            } else if (
                              lower.includes("small") ||
                              lower.includes("minor") ||
                              lower.includes("shallow")
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
                          <span>At least 5 characters. Avoid personal information.</span>
                          <span>{form.description.trim().length}/500</span>
                        </div>
                      </>
                    ) : step === 2 ? (
                      <>
                        <div className="section-number">STEP 02</div>
                        <h2>A clearer picture. An exact location.</h2>
                        <p className="muted">
                          Add a photo and mark where the issue actually is on the map.
                        </p>

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
                            <img src={preview} alt="Complaint preview" />
                            <div className="button-row">
                              <button
                                type="button"
                                className="secondary"
                                onClick={() => fileInput.current?.click()}
                              >
                                Replace photo
                              </button>
                              <button
                                type="button"
                                className="text-button"
                                onClick={() => setForm({ ...form, file: null, analysis: null })}
                              >
                                Remove
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
                            <strong>Click to upload or drag and drop</strong>
                            <span>JPEG, PNG or WebP · Up to 15 MB</span>
                          </button>
                        )}

                        {form.file && (
                          <p style={{ marginTop: "12px", fontSize: "12px", color: "var(--muted)" }}>
                            Your photo is checked automatically after you submit. If it does not
                            appear to match the issue you selected, the report is kept and flagged
                            for human review.
                          </p>
                        )}



                        <div className="location-heading">
                          <label className="field-label">Issue location *</label>
                          <span className="muted">
                            Click the map to place a pin · Southeast Bengaluru Pilot
                          </span>
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
                            Latitude
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
                            Longitude
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
                          Nearby landmark <small>(optional)</small>
                        </label>
                        <input
                          id="landmark"
                          maxLength={150}
                          value={form.landmark}
                          onChange={(e) =>
                            setForm({ ...form, landmark: e.target.value })
                          }
                          placeholder="e.g. Opposite Sony World signal, Koramangala"
                        />

                        <label className="checkbox">
                          <input
                            type="checkbox"
                            checked={form.confirmed}
                            onChange={(e) =>
                              setForm({ ...form, confirmed: e.target.checked })
                            }
                          />
                          I confirm the pin marks the actual civic issue location.
                        </label>
                      </>
                    ) : (
                      <>
                        <div className="section-number">STEP 03</div>
                        <h2>Ready to make a difference?</h2>
                        <p className="muted">
                          Take a moment to review your complaint before submitting.
                        </p>

                        <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "12px" }}>
                          <span className={"badge " + form.issue_type}>
                            {issueLabels[form.issue_type]}
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
                              🚨 Critical Hazard (95 pts)
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
                              🟡 Minor Defect (40 pts)
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
                              ⚠️ Standard Defect (65 pts)
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
                              ⚠️ Flagged Suspicious (-35 pts)
                            </span>
                          )}
                        </div>

                        <p className="review-description">{form.description}</p>

                        {preview && (
                          <div className="analysis-image">
                            <img src={preview} alt="Issue submission" />
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
                                  ⚡ Estimated priority (before photo check)
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
                                  ⭐ {live.score.toFixed(1)} / 100 ({live.band.toUpperCase()})
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
                          <span>
                            This is an estimate based on the category you selected. After you submit,
                            the photo is checked automatically by a road-defect model. If it does not
                            match the selected issue, the report is flagged for human review and its
                            priority is held until it is checked.
                          </span>
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
                        {step === 1 ? "Back to overview" : "Back"}
                      </button>

                      {step < 3 ? (
                        <button type="button" className="primary" onClick={nextStep}>
                          Continue <ArrowRight size={17} />
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
                          {saving ? "Submitting…" : "Submit Complaint"}
                        </button>
                      )}
                    </div>
                  </section>

                  <aside className="report-help">
                    <div className="help-icon">
                      <ShieldCheck size={27} />
                    </div>
                    <h3>Your report matters.</h3>
                    <p>
                      Clear details help your community understand what needs
                      attention.
                    </p>
                    <div>
                      <Check size={16} />
                      Choose the right issue type
                    </div>
                    <div>
                      <Check size={16} />
                      Use a clear, recent photo
                    </div>
                    <div>
                      <Check size={16} />
                      Double-check the location pin
                    </div>
                    <hr />
                    <small>
                      Reports belong to your account. Sign in with the same account
                      on another device to track them.
                    </small>
                  </aside>
                </div>
              )}
            </>
          ) : (
            <>
              {/* PAGE HEADING */}
              <div className="page-heading">
                <div className="eyebrow">BETTER STREETS START WITH US</div>
                <div className="heading-row">
                  <h1>
                    {page === "Overview"
                      ? "Your city, at a glance."
                      : page === "My Reports"
                      ? "Your voice. Your reports."
                      : "Every report. On the map."}
                  </h1>
                  <span className="region">
                    <MapPin size={15} /> Bengaluru, India · Pilot Zone
                  </span>
                </div>
                <p>
                  {page === "Overview"
                    ? "A shared view of the civic issues around us. Report, track, and help move your city forward."
                    : page === "My Reports"
                    ? "Follow the issues you have reported from this account."
                    : "Explore saved complaints and see what needs attention in your neighbourhood."}
                </p>
              </div>

              {/* STAT METRIC CARDS */}
              {page === "Overview" && (
                <div className="metrics">
                  {statCards.map(([title, k, sub, filter], i) => {
                    const Icon = statIcons[i];
                    return (
                      <button
                        key={k}
                        className={
                          "metric card " +
                          k +
                          " " +
                          ((issue === filter && filter && filter !== "resolved") ||
                          (filter === "resolved" && status === "resolved")
                            ? "metric-active"
                            : "")
                        }
                        onClick={() => {
                          setIssue(filter === "resolved" ? "" : filter);
                          setStatus(filter === "resolved" ? "resolved" : "");
                        }}
                      >
                        <div className="metric-top">
                          <span className="metric-icon">
                            <Icon size={21} />
                          </span>
                          <ArrowUpRight size={16} />
                        </div>
                        <span className="metric-label">{title}</span>
                        <strong>
                          {metrics ? metrics[k] ?? total ?? 0 : busy ? "…" : total ?? 0}
                        </strong>
                        <small>{metrics ? sub : "Active complaints"}</small>
                      </button>
                    );
                  })}
                </div>
              )}

              {/* MAIN WORKSPACE SECTION */}
              <section className="card workspace">
                <div className="workspace-header">
                  <div>
                    <div className="panel-title">
                      <span className="section-icon">
                        <MapIcon size={19} />
                      </span>
                      <h2>
                        {page === "My Reports"
                          ? "My reports"
                          : "Neighbourhood reports"}
                      </h2>
                      <span className="outline-badge">
                        {total === null
                          ? "Loading…"
                          : `${total} ${total === 1 ? "report" : "reports"}`}
                      </span>
                    </div>
                    <p>
                      {total === null
                        ? "Your community's reports, in one place."
                        : `Showing ${rows.length} of ${total} matching reports`}
                    </p>
                  </div>
                  <button
                    className="text-button refresh"
                    onClick={reload}
                    disabled={busy}
                  >
                    <RefreshCw size={15} className={busy ? "spin" : ""} />
                    Refresh
                  </button>
                </div>

                {/* FILTER BAR */}
                <div className="filter-bar">
                  <div className="search-box">
                    <Search size={17} />
                    <input
                      aria-label="Search complaints"
                      placeholder="Search by reference or description…"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                    {search && (
                      <button
                        className="icon-button"
                        onClick={() => setSearch("")}
                        aria-label="Clear search"
                      >
                        <X size={14} />
                      </button>
                    )}
                  </div>

                  <select
                    aria-label="Issue type filter"
                    value={issue}
                    onChange={(e) => setIssue(e.target.value)}
                  >
                    <option value="">All issue types</option>
                    {Object.entries(issueLabels).map(([k, v]) => (
                      <option value={k} key={k}>
                        {v}
                      </option>
                    ))}
                  </select>

                  <select
                    aria-label="Status filter"
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                  >
                    <option value="">All statuses</option>
                    {Object.entries(statusLabels).map(([k, v]) => (
                      <option value={k} key={k}>
                        {v}
                      </option>
                    ))}
                  </select>

                  <input
                    className="date-filter"
                    type="date"
                    title="Submitted from"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                  />

                  <input
                    className="date-filter"
                    type="date"
                    title="Submitted through"
                    value={until}
                    min={date}
                    onChange={(e) => setUntil(e.target.value)}
                  />

                  {filterActive && (
                    <button className="text-button" onClick={clearFilters}>
                      Clear filters
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
                    Map
                  </button>
                  <button
                    className={view === "list" ? "active" : ""}
                    onClick={() => setView("list")}
                  >
                    <FileText size={16} />
                    List
                  </button>
                </div>

                {error && (
                  <div className="error-box" role="alert">
                    {error}
                    <button className="text-button" onClick={reload}>
                      Retry
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
                        Bengaluru Southeast Pilot · High-Traffic Weighted Corridors
                      </span>
                      <small>Location is never continuously tracked.</small>
                    </div>
                  </div>

                  <div className="complaint-list">
                    <div className="list-heading">
                      <h3>
                        {page === "My Reports"
                          ? "Your complaints"
                          : "Recent complaints"}
                      </h3>
                      <select
                        aria-label="Sort complaints"
                        value={sort}
                        onChange={(e) => setSort(e.target.value)}
                      >
                        <option value="priority">Priority (Highest first)</option>
                        <option value="newest">Newest first</option>
                        <option value="oldest">Oldest first</option>
                      </select>
                    </div>

                    {busy ? (
                      <div className="skeletons">
                        {[1, 2, 3].map((x) => (
                          <div className="skeleton" key={x} />
                        ))}
                      </div>
                    ) : rows.length ? (
                      rows.map((r) => (
                        <button
                          key={r.id}
                          className={
                            "complaint-row " +
                            (selected?.id === r.id ? "selected" : "")
                          }
                          onClick={() => {
                            setSelected(r);
                            openDetails(r);
                          }}
                        >
                          <div className="complaint-row-top">
                            <span className={"badge " + r.issue_type}>
                              {issueLabels[r.issue_type] || r.issue_type}
                            </span>
                            {r.priority_score !== undefined && (
                              <span
                                className={"priority-pill " + (r.priority_band || "high")}
                                title={r.priority_reason || `Prioritisation Score: ${r.priority_score.toFixed(1)}/100`}
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: "3px",
                                  background: r.priority_score >= 90 ? "#fef2f2" : r.priority_score >= 75 ? "#fffbeb" : "#f0fdf4",
                                  color: r.priority_score >= 90 ? "#991b1b" : r.priority_score >= 75 ? "#92400e" : "#166534",
                                  fontSize: "11px",
                                  fontWeight: 700,
                                  padding: "2px 7px",
                                  borderRadius: "4px",
                                  border: `1px solid ${r.priority_score >= 90 ? "#fecaca" : r.priority_score >= 75 ? "#fde68a" : "#bbf7d0"}`
                                }}
                              >
                                ⭐ {r.priority_score.toFixed(1)} Priority
                              </span>
                            )}
                            {r.duplicate_count > 0 && (
                              <span
                                style={{
                                  background: "#fee2e2",
                                  color: "#991b1b",
                                  fontSize: "11px",
                                  fontWeight: 700,
                                  padding: "2px 6px",
                                  borderRadius: "4px",
                                  border: "1px solid #fca5a5",
                                }}
                              >
                                👥 {r.duplicate_count} Duplicates
                              </span>
                            )}
                            {r.is_suspicious && (
                              <span
                                style={{
                                  background: "#fef3c7",
                                  color: "#b45309",
                                  fontSize: "11px",
                                  fontWeight: 700,
                                  padding: "2px 6px",
                                  borderRadius: "4px",
                                  border: "1px solid #fde68a",
                                }}
                              >
                                ⚠️ Suspicious
                              </span>
                            )}
                            <small>
                              {new Date(r.created_at).toLocaleDateString()}
                            </small>
                          </div>
                          <h4>{r.description}</h4>
                          <small>Report #{r.id.slice(0, 8)}</small>
                          <span className="reference">
                            {r.public_reference || r.id}
                          </span>

                          {isAdmin && r.duplicate_count > 0 && (
                            <div style={{ marginTop: "6px", marginBottom: "4px" }} onClick={(e) => e.stopPropagation()}>
                              <button
                                type="button"
                                className="secondary"
                                style={{
                                  background: "#fee2e2",
                                  borderColor: "#fca5a5",
                                  color: "#991b1b",
                                  fontSize: "11px",
                                  fontWeight: 700,
                                  padding: "4px 8px",
                                  borderRadius: "4px",
                                  cursor: "pointer",
                                }}
                                onClick={() => triggerDeduplicateForReport(r)}
                              >
                                🗑️ Delete {r.duplicate_count} Duplicates (Keep #{r.public_reference || r.id.slice(0, 8)})
                              </button>
                            </div>
                          )}

                          <div className="complaint-row-bottom">
                            <span className={"status " + (r.status || "open")}>
                              <i />
                              {statusLabels[r.status] || r.status || "Open"}
                            </span>
                            <ArrowUpRight size={16} />
                          </div>
                        </button>
                      ))
                    ) : (
                      <div className="list-empty">
                        <span className="empty-art">
                          <MapPin size={31} />
                          <span className="empty-check">
                            <Check size={12} />
                          </span>
                        </span>
                        <p>No complaints match your filters.</p>
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
                      <h3>From reported to resolved</h3>
                    </div>
                    <p>Every report has a next step.</p>
                    <div className="status-items">
                      {["open", "in_progress", "resolved", "rejected"].map((k) => (
                        <button key={k} onClick={() => setStatus(k)}>
                          <span className={"status " + k}>
                            <i />
                            {statusLabels[k]}
                          </span>
                          <strong>
                            {metrics ? metrics[k] ?? 0 : "—"}
                          </strong>
                        </button>
                      ))}
                    </div>
                  </section>

                  <section className="community-card">
                    <span className="community-icon">
                      <Construction size={28} />
                    </span>
                    <div>
                      <span className="eyebrow">
                        A LITTLE ACTION GOES A LONG WAY
                      </span>
                      <h3>
                        {isAdmin
                          ? "Administrator Review & Priority Triage"
                          : "Spotted an issue on your street?"}
                      </h3>
                      <p>
                        {isAdmin
                          ? "Review evidence, adjust priorities, resolve duplicates, or moderate flagged reports."
                          : "Help put it on the map. It only takes a few minutes."}
                      </p>
                      <button className="text-button" onClick={report}>
                        {isAdmin ? "View complaints" : "Create a report"}{" "}
                        <ArrowRight size={16} />
                      </button>
                    </div>
                  </section>
                </div>
              )}

              {/* FOOTER */}
              <footer>
                <span>
                  <span className="footer-brand">NAGARSAATHI</span> · Built for
                  better neighbourhoods.
                </span>
                <span>
                  Bengaluru Pilot · Traffic Prioritised
                </span>
              </footer>
            </>
          )}
        </main>
      </div>

      {/* TOAST ALERT */}
      {toast && (
        <div className="toast" role="status">
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
              aria-label="Close dialog"
            >
              <X />
            </button>

            <div className="eyebrow">COMPLAINT DETAILS</div>
            <h2 id="dialog-title">
              {detail.public_reference || `Report #${detail.id.slice(0, 8)}`}
            </h2>

            {/* Suspicious Mismatch Warning Alert */}
            {detail.is_suspicious && (
              <div
                style={{
                  background: "#fffbeb",
                  border: "1px solid #f59e0b",
                  color: "#92400e",
                  padding: "12px 14px",
                  borderRadius: "8px",
                  margin: "12px 0 16px",
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "10px",
                }}
              >
                <AlertTriangle size={20} color="#d97706" style={{ flexShrink: 0, marginTop: "2px" }} />
                <div>
                  <strong style={{ display: "block", fontSize: "14px", marginBottom: "2px" }}>
                    Flagged as Suspicious
                  </strong>
                  <span style={{ fontSize: "13px" }}>
                    {detail.suspicious_reason ||
                      "Visual detector predicted a category that contradicts the citizen's claimed category. Awaiting administrator audit."}
                  </span>
                </div>
              </div>
            )}

            <div className="button-row">
              <span className={"badge " + detail.issue_type}>
                {issueLabels[detail.issue_type] || detail.issue_type}
              </span>
              <span className={"status " + (detail.status || "open")}>
                <i />
                {statusLabels[detail.status] || detail.status || "Open"}
              </span>
            </div>

            <p className="review-description">{detail.description}</p>

            {detail.photo_url && (
              <AuthImage
                className="detail-photo"
                src={reportPhotoUrl(detail.photo_url)}
                alt="Complaint evidence"
              />
            )}

            {detail.latitude && detail.longitude && (
              <p className="location-line">
                <MapPin size={17} />
                {Number(detail.latitude).toFixed(6)}, {Number(detail.longitude).toFixed(6)}
              </p>
            )}

            <dl>
              <dt>Submitted</dt>
              <dd>{new Date(detail.created_at).toLocaleString()}</dd>
            </dl>

            {/* PRIORITISATION BREAKDOWN CARD */}
            {(() => {
              const pe = calculatePriorityScore(detail);
              return (
                <div
                  style={{
                    background: "#f8fafc",
                    border: "1px solid #cbd5e1",
                    borderRadius: "8px",
                    padding: "14px",
                    margin: "14px 0",
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
                    <strong style={{ fontSize: "13px", color: "#1e293b" }}>
                      ⭐ Prioritisation Engine Score
                    </strong>
                    <span
                      style={{
                        padding: "3px 8px",
                        borderRadius: "4px",
                        fontWeight: 700,
                        fontSize: "12px",
                        background:
                          pe.score >= 90
                            ? "#fef2f2"
                            : pe.score >= 75
                            ? "#fffbeb"
                            : "#f0fdf4",
                        color:
                          pe.score >= 90
                            ? "#991b1b"
                            : pe.score >= 75
                            ? "#92400e"
                            : "#166534",
                        border: `1px solid ${
                          pe.score >= 90
                            ? "#fecaca"
                            : pe.score >= 75
                            ? "#fde68a"
                            : "#bbf7d0"
                        }`,
                      }}
                    >
                      {pe.score.toFixed(1)} / 100 ({pe.band.toUpperCase()})
                    </span>
                  </div>
                  <ul
                    style={{
                      margin: 0,
                      paddingLeft: "16px",
                      fontSize: "12px",
                      color: "#475569",
                    }}
                  >
                    {pe.reasons.map((r, i) => (
                      <li key={i} style={{ marginBottom: "3px" }}>
                        {r}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })()}

            {/* ADMIN ONLY CONTROLS */}
            {isAdmin && (
              <>
                <div
                  style={{
                    background: "#f8fafc",
                    border: "1px solid #cbd5e1",
                    borderRadius: "8px",
                    padding: "16px",
                    margin: "16px 0",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                      marginBottom: "12px",
                      color: "#b45309",
                      fontWeight: 700,
                      fontSize: "13px",
                    }}
                  >
                    <ShieldCheck size={18} />
                    <span>ADMINISTRATOR REVIEW & TRIAGE</span>
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: "12px",
                      marginBottom: "12px",
                    }}
                  >
                    <div>
                      <label
                        style={{
                          display: "block",
                          fontSize: "11px",
                          fontWeight: 600,
                          marginBottom: "4px",
                        }}
                      >
                        Status
                      </label>
                      <select
                        value={reviewForm.status}
                        onChange={(e) =>
                          setReviewForm({ ...reviewForm, status: e.target.value })
                        }
                        style={{
                          width: "100%",
                          padding: "8px",
                          borderRadius: "6px",
                          border: "1px solid #cbd5e1",
                        }}
                      >
                        <option value="open">Open</option>
                        <option value="in_progress">In progress</option>
                        <option value="resolved">Resolved</option>
                        <option value="rejected">Rejected</option>
                      </select>
                    </div>

                    <div>
                      <label
                        style={{
                          display: "block",
                          fontSize: "11px",
                          fontWeight: 600,
                          marginBottom: "4px",
                        }}
                      >
                        Priority
                      </label>
                      <select
                        value={reviewForm.priority}
                        onChange={(e) =>
                          setReviewForm({ ...reviewForm, priority: e.target.value })
                        }
                        style={{
                          width: "100%",
                          padding: "8px",
                          borderRadius: "6px",
                          border: "1px solid #cbd5e1",
                        }}
                      >
                        <option value="low">Low</option>
                        <option value="normal">Normal</option>
                        <option value="high">High</option>
                        <option value="urgent">Urgent</option>
                      </select>
                    </div>
                  </div>

                  <div style={{ marginBottom: "12px" }}>
                    <label
                      style={{
                        display: "block",
                        fontSize: "11px",
                        fontWeight: 600,
                        marginBottom: "4px",
                      }}
                    >
                      Priority Reason / Review Note
                    </label>
                    <input
                      type="text"
                      placeholder="Explain priority adjustment or review note"
                      value={reviewForm.priority_reason}
                      onChange={(e) =>
                        setReviewForm({
                          ...reviewForm,
                          priority_reason: e.target.value,
                        })
                      }
                      style={{
                        width: "100%",
                        padding: "8px",
                        borderRadius: "6px",
                        border: "1px solid #cbd5e1",
                      }}
                    />
                  </div>

                  <div style={{ display: "flex", gap: "8px" }}>
                    <button
                      className="primary"
                      style={{ flex: 1, padding: "10px", justifyContent: "center" }}
                      disabled={reviewSaving}
                      onClick={handleSaveReview}
                    >
                      {reviewSaving ? "Saving..." : "Save Admin Review"}
                    </button>
                    <button
                      className="secondary"
                      style={{
                        background: "#fee2e2",
                        borderColor: "#fca5a5",
                        color: "#b91c1c",
                        padding: "10px",
                        fontWeight: 600,
                      }}
                      onClick={() => setDeleteModal(true)}
                    >
                      <Trash2 size={16} /> Delete
                    </button>
                  </div>
                </div>

                {/* DEDUPLICATION ACTIONS */}
                <div
                  style={{
                    background: "#f0fdf4",
                    border: "1px solid #bbf7d0",
                    borderRadius: "8px",
                    padding: "14px",
                    margin: "16px 0",
                  }}
                >
                  <strong style={{ display: "block", color: "#166534", marginBottom: "4px" }}>
                    Duplicate Resolution
                  </strong>
                  <p style={{ fontSize: "12px", color: "#15803d", margin: "0 0 10px" }}>
                    Clean up multiple citizen reports for the same incident. Keeps this report and deletes all duplicate reports.
                  </p>
                  <button
                    type="button"
                    className="secondary"
                    style={{
                      background: "#fee2e2",
                      borderColor: "#fca5a5",
                      color: "#991b1b",
                      fontWeight: 600,
                      width: "100%",
                      justifyContent: "center",
                    }}
                    onClick={handleDeduplicateKeepOne}
                  >
                    🗑️ Delete All Duplicates (Keep Only This Report)
                  </button>
                </div>
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
                Show on map
              </button>

              <button
                className="secondary"
                onClick={() =>
                  navigator.clipboard
                    .writeText(String(detail.public_reference || detail.id))
                    .then(() => notify("Reference copied"))
                    .catch(() => notify("Clipboard unavailable"))
                }
              >
                <Copy size={16} />
                Copy reference
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
            <div className="eyebrow">MODERATION ACTION</div>
            <h2>Soft Delete Complaint</h2>
            <p style={{ color: "var(--muted)", fontSize: "13px", marginBottom: "14px" }}>
              Removes this complaint from public lists while preserving auditable records.
            </p>
            <label style={{ display: "block", marginBottom: "12px" }}>
              Deletion Reason (Required for audit log)
              <textarea
                rows={3}
                placeholder="Explain why this complaint is being removed..."
                value={deleteReason}
                onChange={(e) => setDeleteReason(e.target.value)}
                style={{ width: "100%", marginTop: "6px" }}
              />
            </label>
            <div className="button-row" style={{ justifyContent: "flex-end", gap: "8px" }}>
              <button className="secondary" onClick={() => setDeleteModal(false)}>
                Cancel
              </button>
              <button
                className="primary"
                style={{ background: "#dc2626", borderColor: "#dc2626" }}
                disabled={deleteBusy || deleteReason.trim().length < 3}
                onClick={handleSoftDelete}
              >
                {deleteBusy ? "Deleting..." : "Confirm Soft Delete"}
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
              aria-label="Close dialog"
            >
              <X />
            </button>

            <div className="eyebrow">CITIZEN & ADMIN ACCESS</div>
            <h2 id="auth-title">Sign In to NAGARSAATHI</h2>
            <p style={{ fontSize: "13px", color: "var(--muted)", marginBottom: "16px" }}>
              Sign in with your Google account.{authOptions.demo_enabled ? " Demo accounts are available in this environment." : ""}
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
                Demo Accounts
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
                Google Sign In
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
                  Instant one-click access with pre-configured demo permissions:
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
                  <span>Sign In as Demo Admin (Review & Triage)</span>
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
                  <span>Sign In as Demo Citizen (Standard User)</span>
                </button>
              </div>
            ) : (
              <div>
                <p style={{ fontSize: "12px", color: "var(--muted)", marginBottom: "14px" }}>
                  Sign in with verified Google credentials (Google Identity Services API):
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
                    Google sign-in is not configured on the server. Set GOOGLE_CLIENT_ID and restart the API.
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
