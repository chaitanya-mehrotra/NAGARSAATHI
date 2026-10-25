import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  LayoutDashboard,
  Map,
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
  WifiOff,
  ChevronRight,
  ChevronLeft,
  X,
  Upload,
  LocateFixed,
  ShieldCheck,
  Menu,
  SlidersHorizontal,
  Clock,
  Copy,
  ExternalLink,
  RefreshCw,
  LoaderCircle,
} from "lucide-react";
import ComplaintMap from "./Map";
import {
  configured,
  identity,
  request,
  analyze,
  submit,
  login,
  register,
  logout,
  getStoredToken,
  getStoredUser,
  updateReport,
} from "./services";
import {
  issueLabels,
  statusLabels,
  validatePhoto,
  verification,
} from "./validation";
import "./style.css";
const nav = [
  ["Overview", LayoutDashboard],
  ["Report Issue", Plus],
  ["Complaint Map", Map],
  ["My Reports", FileText],
];
const fresh = () => ({
  issue_type: "pothole",
  description: "",
  file: null,
  latitude: null,
  longitude: null,
  landmark: "",
  confirmed: false,
  analysis: null,
});
function App() {
  const [page, setPage] = useState("Overview"),
    [mobile, setMobile] = useState(false),
    [search, setSearch] = useState(""),
    [issue, setIssue] = useState(""),
    [status, setStatus] = useState(""),
    [date, setDate] = useState(""),
    [until, setUntil] = useState(""),
    [sort, setSort] = useState("newest"),
    [view, setView] = useState("map"),
    [rows, setRows] = useState([]),
    [total, setTotal] = useState(null),
    [metrics, setMetrics] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [connection, setConnection] = useState("Live"),
    [selected, setSelected] = useState(null),
    [detail, setDetail] = useState(null),
    [toast, setToast] = useState(""),
    [refresh, setRefresh] = useState(0),
    [offset, setOffset] = useState(0),
    [setup, setSetup] = useState(false);
  const [user, setUser] = useState(getStoredUser);
  const [authModal, setAuthModal] = useState(false);
  const [authTab, setAuthTab] = useState("login");
  const [authForm, setAuthForm] = useState({ name: "", email: "", password: "" });
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [reviewForm, setReviewForm] = useState({
    status: "open",
    priority: "normal",
    priority_reason: "",
    duplicate_of: null,
  });
  const [reviewSaving, setReviewSaving] = useState(false);
  const [form, setForm] = useState(fresh),
    [step, setStep] = useState(1),
    [formError, setFormError] = useState(""),
    [saving, setSaving] = useState(false),
    [checking, setChecking] = useState(false),
    [aiError, setAiError] = useState(""),
    [preview, setPreview] = useState(""),
    [detections, setDetections] = useState(true),
    [success, setSuccess] = useState(null);
  const key = useRef(crypto.randomUUID()),
    abort = useRef(null),
    fileInput = useRef(null),
    closeRef = useRef(null),
    previousFocus = useRef(null);
  useEffect(() => () => abort.current?.abort(), []);
  const reload = () => setRefresh((x) => x + 1);
  const changePage = (p) => {
    setPage(p);
    setMobile(false);
    setOffset(0);
  };
  const report = () => changePage("Report Issue");
  function notify(t) {
    setToast(t);
    setTimeout(() => setToast(""), 4000);
  }

  async function handleLogin(e, demoEmail, demoPass) {
    if (e) e.preventDefault();
    setAuthError("");
    setAuthLoading(true);
    try {
      const email = demoEmail || authForm.email;
      const pass = demoPass || authForm.password;
      const res = await login(email, pass);
      setUser(res.user);
      setAuthModal(false);
      notify(`Signed in as ${res.user.name}`);
      reload();
    } catch (err) {
      setAuthError(err.message);
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleRegister(e) {
    if (e) e.preventDefault();
    setAuthError("");
    setAuthLoading(true);
    try {
      await register(authForm.name, authForm.email, authForm.password);
      const res = await login(authForm.email, authForm.password);
      setUser(res.user);
      setAuthModal(false);
      notify(`Account created! Welcome, ${res.user.name}`);
      reload();
    } catch (err) {
      setAuthError(err.message);
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleLogout() {
    await logout();
    setUser(null);
    notify("Signed out");
    reload();
  }

  useEffect(() => {
    if (detail) {
      setReviewForm({
        status: detail.status || "open",
        priority: detail.priority || "normal",
        priority_reason: detail.priority_reason || "",
        duplicate_of: detail.duplicate_of || null,
      });
    }
  }, [detail]);

  async function handleSaveReview() {
    if (!detail) return;
    setReviewSaving(true);
    try {
      const updated = await updateReport(detail.id, reviewForm);
      setDetail(updated);
      notify("Complaint review updated successfully");
      reload();
    } catch (err) {
      notify(`Error updating: ${err.message}`);
    } finally {
      setReviewSaving(false);
    }
  }

  useEffect(() => {
    if (!form.file) {
      setPreview("");
      return;
    }
    const url = URL.createObjectURL(form.file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [form.file]);
  useEffect(() => {
    setOffset(0);
  }, [search, issue, status, date, until, sort, page]);
  useEffect(() => {
    identity().then((sess) => {
      if (sess?.user) {
        setUser(sess.user);
      } else {
        // Auto-login demo citizen if first time visiting so user immediately sees live data
        login("citizen1@example.com", "securepassword123")
          .then((res) => {
            setUser(res.user);
            reload();
          })
          .catch(() => {});
      }
    });
    setConnection("Live");
  }, []);
  useEffect(() => {
    if (!configured || !user) return;
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
    const timer = setTimeout(
      () =>
        Promise.all([request("/complaints?" + params), request("/metrics")])
          .then(([data, m]) => {
            if (active) {
              setRows(data.items || []);
              setTotal(data.total || 0);
              setMetrics(m);
              setError("");
            }
          })
          .catch((e) => {
            if (active) setError(e.message);
          })
          .finally(() => active && setBusy(false)),
      250,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [search, issue, status, date, until, sort, page, offset, refresh, user]);
  useEffect(() => {
    const id = location.hash.match(/^#\/complaints\/([0-9a-zA-Z-]+)$/)?.[1];
    if (id && configured && user)
      request("/complaints/" + id)
        .then(setDetail)
        .catch((e) => setError(e.message));
  }, [refresh, user]);
  useEffect(() => {
    if (!detail && !setup) return;
    previousFocus.current = document.activeElement;
    closeRef.current?.focus();
    const handle = (e) => {
      if (e.key === "Escape") {
        setDetail(null);
        setSetup(false);
        history.replaceState(null, "", location.pathname);
      }
      if (e.key === "Tab") {
        const dialog = document.querySelector('[role="dialog"]');
        const els = [
          ...dialog.querySelectorAll("button,a,input,select,textarea"),
        ].filter((x) => !x.disabled);
        const first = els[0],
          last = els.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handle);
    return () => {
      document.removeEventListener("keydown", handle);
      previousFocus.current?.focus();
    };
  }, [detail, setup]);
  function openDetails(r) {
    setDetail(r);
    history.replaceState(null, "", "#/complaints/" + r.id);
  }
  function close() {
    setDetail(null);
    setSetup(false);
    history.replaceState(null, "", location.pathname);
  }
  function chooseFile(f) {
    const err = validatePhoto(f);
    if (err) {
      setFormError(err);
      return;
    }
    abort.current?.abort();
    setChecking(false);
    setAiError("");
    setFormError("");
    setForm((v) => ({ ...v, file: f, analysis: null }));
  }
  async function checkPhoto() {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setChecking(true);
    setAiError("");
    try {
      const result = await analyze(form.file, controller.signal);
      if (!controller.signal.aborted)
        setForm((f) => ({ ...f, analysis: result }));
    } catch (e) {
      if (e.name !== "AbortError") setAiError(e.message);
    } finally {
      if (!controller.signal.aborted) setChecking(false);
    }
  }
  function next() {
    let e = "";
    if (
      step === 1 &&
      (form.description.trim().length < 10 ||
        form.description.trim().length > 500)
    )
      e = "Describe the issue in 10–500 characters.";
    if (step === 2)
      e =
        validatePhoto(form.file) ||
        (!Number.isFinite(form.latitude) ||
        !Number.isFinite(form.longitude) ||
        Math.abs(form.latitude) > 90 ||
        Math.abs(form.longitude) > 180
          ? "Place a pin or enter valid coordinates at the issue location."
          : !form.confirmed
            ? "Confirm that the pin marks the actual issue location."
            : "");
    setFormError(e);
    if (!e) setStep(step + 1);
  }
  async function save() {
    if (saving) return;
    if (!user) {
      setAuthModal(true);
      setFormError("Please sign in or register to submit your complaint.");
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      const r = await submit({
        ...form,
        description: form.description.trim(),
      });
      setSuccess(r);
      reload();
    } catch (e) {
      setFormError(e.message);
    } finally {
      setSaving(false);
    }
  }
  function reset() {
    abort.current?.abort();
    setForm(fresh());
    setStep(1);
    setSuccess(null);
    setFormError("");
    setAiError("");
    key.current = crypto.randomUUID();
  }
  const filterActive = search || issue || status || date || until;
  const clear = () => {
    setSearch("");
    setIssue("");
    setStatus("");
    setDate("");
    setUntil("");
  };
  const icons = [FileText, Construction, Droplets, CheckCheck];
  const cards = [
    ["Total complaints", "total", "All reported issues", ""],
    ["Pothole reports", "pothole", "Road surface issues", "pothole"],
    [
      "Waterlogging reports",
      "waterlogging",
      "Drainage & flooding",
      "waterlogging",
    ],
    ["Resolved complaints", "resolved", "Issues taken care of", "resolved"],
  ];
  return (
    <div className="app">
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
        <div className="workspace-label" style={user?.role === "admin" ? { color: "#d97706", fontWeight: 700 } : undefined}>
          {user?.role === "admin" ? "ADMINISTRATOR WORKSPACE" : "CITIZEN WORKSPACE"}
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
              Be the eyes of your city. Every issue you report is a step
              forward.
            </p>
            <button onClick={report}>
              Make a difference <ArrowRight size={15} />
            </button>
          </div>
          <div
            className="session"
            onClick={() => (!user ? setAuthModal(true) : null)}
            style={{ cursor: user ? "default" : "pointer" }}
          >
            <span
              className="avatar"
              style={user?.role === "admin" ? { background: "#d97706", color: "#fff" } : undefined}
            >
              {user ? user.name[0].toUpperCase() : "C"}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {user ? user.name : "Sign In / Register"}
              </div>
              <small style={{ display: "block" }}>
                {user ? (user.role === "admin" ? "Administrator" : "Citizen account") : "Click to authenticate"}
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
      <div className="main">
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
            {user?.role === "admin" && (
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
              className={
                "connection " + (connection === "Live" ? "online" : "")
              }
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
            <button className="primary" onClick={report}>
              <Plus size={17} />
              Report Issue
            </button>
          </div>
        </header>
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
                    <strong>{success.reference || `Report #${success.id}`}</strong> · Status:{" "}
                    <span className={"status " + (success.status || "open")}>
                      <i />
                      {statusLabels[success.status] || success.status || "Open"}
                    </span>
                  </div>

                  {success.analysis_status === "completed" && (
                    <div className="ai-panel" style={{ textAlign: "left", margin: "16px auto", maxWidth: "480px" }}>
                      <strong>YOLO11n AI Detection Results</strong>
                      <p>
                        {success.analysis?.detections?.length || 0} issues detected · {success.analysis?.model_version || "YOLO11n"}
                      </p>
                      {success.analysis?.detections?.length === 0 && (
                        <p className="muted" style={{ margin: "6px 0" }}>
                          No road issues detected in photo. Complaint is safely preserved in records.
                        </p>
                      )}
                      {success.analysis?.detections?.map((d, i) => (
                        <p key={i} style={{ margin: "4px 0" }}>
                          {(d.label || d.class_name || "Issue").replace(/^./, (c) => c.toUpperCase())} · {Math.round(d.confidence * 100)}% model confidence
                        </p>
                      ))}
                      <small>Model confidence assists review and is never confused with complaint priority.</small>
                    </div>
                  )}

                  {success.analysis_status === "failed" && (
                    <div className="ai-panel" style={{ textAlign: "left", margin: "16px auto", maxWidth: "480px", borderLeft: "4px solid #ef4444" }}>
                      <strong style={{ color: "#ef4444" }}>AI Analysis Note</strong>
                      <p>The AI model encountered an issue during analysis, but your complaint and road photo were permanently saved without interruption.</p>
                    </div>
                  )}

                  {success.analysis_status === "unavailable" && (
                    <div className="ai-panel" style={{ textAlign: "left", margin: "16px auto", maxWidth: "480px" }}>
                      <strong>AI Analysis Unavailable</strong>
                      <p>Model analysis was offline, but your complaint and road photo were permanently saved.</p>
                    </div>
                  )}

                  {success.duplicate_of && (
                    <div className="privacy-note" style={{ margin: "16px auto", maxWidth: "480px" }}>
                      <Info size={18} />
                      <span>Nearby possible duplicate report identified (Report #{success.duplicate_of}). Administrator will review both.</span>
                    </div>
                  )}

                  <div className="button-row" style={{ marginTop: "24px" }}>
                    <button
                      className="primary"
                      onClick={() => openDetails(success)}
                    >
                      View Complaint Details
                    </button>
                    <button
                      className="secondary"
                      onClick={() => {
                        changePage("Complaint Map");
                        setSelected(success);
                      }}
                    >
                      Show on Map
                    </button>
                    <button className="text-button" onClick={reset}>
                      Report another issue
                    </button>
                  </div>
                </section>
              ) : (
                <div className="report-layout">
                  <section className="card report-card">
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
                          Choose the issue you noticed and tell us a little
                          more.
                        </p>
                        <label className="field-label">
                          Issue type <span>*</span>
                        </label>
                        <div className="issue-choices">
                          {Object.entries(issueLabels).map(([k, v]) => (
                            <button
                              key={k}
                              className={
                                "issue-choice " +
                                k +
                                " " +
                                (form.issue_type === k ? "chosen" : "")
                              }
                              onClick={() =>
                                setForm({ ...form, issue_type: k })
                              }
                            >
                              {k === "waterlogging" ? (
                                <Droplets />
                              ) : k === "pothole" ? (
                                <Construction />
                              ) : (
                                <MapPin />
                              )}
                              <strong>{v}</strong>
                              <small>
                                {k === "pothole"
                                  ? "Damaged road surface"
                                  : k === "waterlogging"
                                    ? "Standing or flooding water"
                                    : "Pothole and waterlogging"}
                              </small>
                              {form.issue_type === k && (
                                <Check className="choice-check" size={17} />
                              )}
                            </button>
                          ))}
                        </div>
                        <label className="field-label" htmlFor="description">
                          Describe the issue <span>*</span>
                        </label>
                        <textarea
                          id="description"
                          maxLength={500}
                          rows={6}
                          placeholder="What did you notice? Include details that will help someone find and understand the issue."
                          value={form.description}
                          onChange={(e) =>
                            setForm({ ...form, description: e.target.value })
                          }
                        />
                        <div className="field-foot">
                          <span>
                            At least 10 characters. Please avoid personal
                            information.
                          </span>
                          <span>{form.description.trim().length}/500</span>
                        </div>
                      </>
                    ) : step === 2 ? (
                      <>
                        <div className="section-number">STEP 02</div>
                        <h2>A clearer picture. An exact location.</h2>
                        <p className="muted">
                          Add a photo and mark where the issue actually is.
                        </p>
                        <input
                          ref={fileInput}
                          hidden
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          onChange={(e) =>
                            e.target.files[0] && chooseFile(e.target.files[0])
                          }
                        />
                        {preview ? (
                          <div className="photo-preview">
                            <img src={preview} alt="Issue upload preview" />
                            <div className="button-row">
                              <button
                                className="secondary"
                                onClick={() => fileInput.current.click()}
                              >
                                Replace photo
                              </button>
                              <button
                                className="text-button"
                                onClick={() => {
                                  abort.current?.abort();
                                  setForm({
                                    ...form,
                                    file: null,
                                    analysis: null,
                                  });
                                  setChecking(false);
                                }}
                              >
                                Remove
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            className="upload-zone"
                            onClick={() => fileInput.current.click()}
                            onDragOver={(e) => e.preventDefault()}
                            onDrop={(e) => {
                              e.preventDefault();
                              chooseFile(e.dataTransfer.files[0]);
                            }}
                          >
                            <Upload size={28} />
                            <strong>Click to upload or drag and drop</strong>
                            <span>JPEG, PNG or WebP · Up to 10 MB</span>
                          </button>
                        )}
                        <div className="location-heading">
                          <label className="field-label">
                            Issue location *
                          </label>
                          <span className="muted">
                            Click the map to place a pin · Drag to adjust
                          </span>
                        </div>
                        <div className="picker-map">
                          <ComplaintMap
                            point={
                              form.latitude === null ||
                              form.longitude === null ||
                              Math.abs(form.latitude) > 90 ||
                              Math.abs(form.longitude) > 180
                                ? null
                                : [form.latitude, form.longitude]
                            }
                            onPoint={(p) =>
                              setForm((f) => ({
                                ...f,
                                latitude: p[0],
                                longitude: p[1],
                                confirmed: false,
                              }))
                            }
                          />
                        </div>
                        <div className="coordinates">
                          <label>
                            Latitude
                            <input
                              type="number"
                              aria-label="Issue latitude"
                              min="-90"
                              max="90"
                              step="any"
                              placeholder="Click map or enter"
                              value={form.latitude ?? ""}
                              onChange={(e) =>
                                setForm({
                                  ...form,
                                  latitude:
                                    e.target.value === ""
                                      ? null
                                      : Number(e.target.value),
                                  confirmed: false,
                                })
                              }
                            />
                          </label>
                          <label>
                            Longitude
                            <input
                              type="number"
                              aria-label="Issue longitude"
                              min="-180"
                              max="180"
                              step="any"
                              placeholder="Click map or enter"
                              value={form.longitude ?? ""}
                              onChange={(e) =>
                                setForm({
                                  ...form,
                                  longitude:
                                    e.target.value === ""
                                      ? null
                                      : Number(e.target.value),
                                  confirmed: false,
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
                          placeholder="e.g. opposite the community park"
                        />
                        <label className="checkbox">
                          <input
                            type="checkbox"
                            checked={form.confirmed}
                            onChange={(e) =>
                              setForm({ ...form, confirmed: e.target.checked })
                            }
                          />
                          I confirm the pin marks the actual issue location.
                        </label>
                      </>
                    ) : (
                      <>
                        <div className="section-number">STEP 03</div>
                        <h2>Ready to make a difference?</h2>
                        <p className="muted">
                          Take a moment to review your complaint.
                        </p>
                        <span className={"badge " + form.issue_type}>
                          {issueLabels[form.issue_type]}
                        </span>
                        <p className="review-description">{form.description}</p>
                        <div className="analysis-image">
                          <img src={preview} alt="Issue to submit" />
                          {detections &&
                            form.analysis?.detections.map((d, i) => (
                              <div
                                key={i}
                                className="bbox"
                                style={{
                                  left:
                                    (d.bbox[0] / form.analysis.image_width) *
                                      100 +
                                    "%",
                                  top:
                                    (d.bbox[1] / form.analysis.image_height) *
                                      100 +
                                    "%",
                                  width:
                                    ((d.bbox[2] - d.bbox[0]) /
                                      form.analysis.image_width) *
                                      100 +
                                    "%",
                                  height:
                                    ((d.bbox[3] - d.bbox[1]) /
                                      form.analysis.image_height) *
                                      100 +
                                    "%",
                                }}
                              >
                                <span>
                                  {d.class_name}{" "}
                                  {Math.round(d.confidence * 100)}%
                                </span>
                              </div>
                            ))}
                        </div>
                        <p className="location-line">
                          <MapPin size={16} />
                          {form.latitude?.toFixed(6)},{" "}
                          {form.longitude?.toFixed(6)}{" "}
                          {form.landmark && "· " + form.landmark}
                        </p>
                        <div className="ai-panel">
                          <div className="panel-title">
                            <strong>
                              <ShieldCheck size={17} />
                              Optional photo check
                            </strong>
                            <button
                              className="secondary"
                              disabled={checking}
                              onClick={checkPhoto}
                            >
                              {checking ? (
                                <LoaderCircle className="spin" size={15} />
                              ) : null}
                              {checking ? "Checking…" : "Check Photo"}
                            </button>
                          </div>
                          <p>
                            Compares the selected issue with the photo. The
                            model does not understand your description.
                            Confidence does not indicate severity.
                          </p>
                          {aiError && (
                            <p role="status" className="error-text">
                              Could not verify: {aiError} You can still submit.
                            </p>
                          )}
                          {form.analysis && (
                            <>
                              <strong>
                                {verification(
                                  form.issue_type,
                                  form.analysis.detections,
                                )}
                              </strong>
                              <p>
                                {form.analysis.detections.length} detections
                              </p>
                              <button
                                className="text-button"
                                onClick={() => setDetections(!detections)}
                              >
                                {detections
                                  ? "Show original"
                                  : "Show detections"}
                              </button>
                              <details>
                                <summary>Model & image details</summary>
                                {form.analysis.model_version} ·{" "}
                                {form.analysis.image_width} ×{" "}
                                {form.analysis.image_height}px
                              </details>
                            </>
                          )}
                          <small>
                            AI assists review and may miss or misidentify
                            issues.
                          </small>
                        </div>
                        <div className="privacy-note">
                          <Info size={18} />
                          <span>
                            Your description, photo and issue location will be
                            shared with other demo users. Please do not include
                            personal information.
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
                        className="text-button"
                        onClick={() =>
                          step === 1
                            ? changePage("Overview")
                            : setStep(step - 1)
                        }
                      >
                        <ChevronLeft size={16} />
                        {step === 1 ? "Back to overview" : "Back"}
                      </button>
                      {step < 3 ? (
                        <button className="primary" onClick={next}>
                          Continue <ArrowRight size={17} />
                        </button>
                      ) : (
                        <button
                          className="primary"
                          disabled={saving}
                          onClick={save}
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
                      Double-check the location
                    </div>
                    <hr />
                    <small>
                      My Reports is tied to this browser session. Clearing the
                      session can remove your access. Cross-device recovery is
                      not available.
                    </small>
                  </aside>
                </div>
              )}
            </>
          ) : (
            <>
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
                    <MapPin size={15} /> Bengaluru, India
                  </span>
                </div>
                <p>
                  {page === "Overview"
                    ? "A shared view of the issues around us. Report, track, and help move your city forward."
                    : page === "My Reports"
                      ? "Follow the issues you have reported from this browser session."
                      : "Explore saved complaints and see what needs attention in your neighbourhood."}
                </p>
              </div>
              {!configured && (
                <div className="setup-banner">
                  <span className="setup-icon">
                    <WifiOff size={19} />
                  </span>
                  <div>
                    <strong>
                      Your workspace is ready. Connect it to bring reports to
                      life.
                    </strong>
                    <p>
                      Supabase isn’t connected yet. Saved reports and live
                      updates will appear here once configured.
                    </p>
                  </div>
                  <button onClick={() => setSetup(true)}>
                    View setup <ArrowUpRight size={16} />
                  </button>
                </div>
              )}
              {page === "Overview" && (
                <div className="metrics">
                  {cards.map(([title, k, sub, filter], i) => {
                    const Icon = icons[i];
                    return (
                      <button
                        key={k}
                        className={
                          "metric card " +
                          k +
                          " " +
                          ((issue === filter &&
                            filter &&
                            filter !== "resolved") ||
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
                        <span className="metric-label">
                          {title}
                          {i === 1 || i === 2 ? (
                            <span
                              title="Reports marked Both contribute to both issue-specific counts."
                              className="info-tip"
                            >
                              <Info size={13} />
                            </span>
                          ) : null}
                        </span>
                        <strong>
                          {metrics ? metrics[k] : busy ? "…" : "—"}
                        </strong>
                        <small>
                          {metrics ? sub : "Awaiting database connection"}
                        </small>
                      </button>
                    );
                  })}
                </div>
              )}
              {page === "My Reports" && (
                <div className="session-notice">
                  <Info size={17} />
                  Reports belong to your anonymous browser session. Clearing it
                  may remove access; there is no cross-device recovery.
                </div>
              )}
              <section className="card workspace">
                <div className="workspace-header">
                  <div>
                    <div className="panel-title">
                      <span className="section-icon">
                        <Map size={19} />
                      </span>
                      <h2>
                        {page === "My Reports"
                          ? "My reports"
                          : "Neighbourhood reports"}
                      </h2>
                      <span className="outline-badge">
                        {total === null
                          ? "Not connected"
                          : total + " complaints"}
                      </span>
                    </div>
                    <p>
                      {total === null
                        ? "Your community’s reports, in one place."
                        : "Showing " +
                          rows.length +
                          " of " +
                          total +
                          " matching complaints"}
                    </p>
                  </div>
                  <button
                    className="text-button refresh"
                    onClick={reload}
                    disabled={!configured || busy}
                  >
                    <RefreshCw size={15} className={busy ? "spin" : ""} />
                    Refresh
                  </button>
                </div>
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
                    aria-label="Reports submitted since"
                    title="Submitted from"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                  />
                  <input
                    className="date-filter"
                    type="date"
                    aria-label="Reports submitted through"
                    title="Submitted through"
                    value={until}
                    min={date}
                    onChange={(e) => setUntil(e.target.value)}
                  />
                  {filterActive && (
                    <button className="text-button" onClick={clear}>
                      Clear filters
                    </button>
                  )}
                </div>
                <div className="mobile-switch">
                  <button
                    className={view === "map" ? "active" : ""}
                    onClick={() => setView("map")}
                  >
                    <Map size={16} />
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
                <div className={"map-list view-" + view}>
                  <div className="main-map">
                    <ComplaintMap
                      {...{ rows, selected }}
                      onSelect={setSelected}
                      onDetails={openDetails}
                    />
                    <div className="map-caption">
                      <span>
                        <span
                          className={
                            "dot " +
                            (connection === "Live" ? "live" : "neutral")
                          }
                        />
                        {connection === "Live"
                          ? "Saved reports update live"
                          : "Saved complaint locations"}
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
                        <option value="newest">Newest first</option>
                        <option value="oldest">Oldest first</option>
                      </select>
                    </div>
                    {busy ? (
                      <div
                        className="skeletons"
                        role="status"
                        aria-label="Loading complaints"
                      >
                        {[1, 2, 3].map((x) => (
                          <div className="skeleton" key={x} />
                        ))}
                      </div>
                    ) : rows.length ? (
                      rows.map((r) => (
                        <button
                          className={
                            "complaint-row " +
                            (selected?.id === r.id ? "selected" : "")
                          }
                          key={r.id}
                          onClick={() => {
                            setSelected(r);
                            openDetails(r);
                          }}
                        >
                          <div className="complaint-row-top">
                            <span className={"badge " + r.issue_type}>
                              {issueLabels[r.issue_type]}
                            </span>
                            <small>
                              {new Date(r.created_at).toLocaleDateString()}
                            </small>
                          </div>
                          <h4>{r.description}</h4>
                          <span className="reference">{r.reference}</span>
                          <div className="complaint-row-bottom">
                            <span className={"status " + r.status}>
                              <i />
                              {statusLabels[r.status]}
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
                        <h3>
                          {!configured
                            ? "A fresh start for your city"
                            : filterActive
                              ? "No matching complaints"
                              : "No reports here yet"}
                        </h3>
                        <p>
                          {!configured
                            ? "Once connected, your community’s saved reports will appear here."
                            : filterActive
                              ? "Try another search or clear your filters."
                              : "Be the first to bring an issue to your community’s attention."}
                        </p>
                        <button
                          className="secondary"
                          onClick={filterActive ? clear : report}
                        >
                          {filterActive ? <X size={15} /> : <Plus size={15} />}{" "}
                          {filterActive ? "Clear filters" : "Report an issue"}
                        </button>
                      </div>
                    )}
                    <div className="pagination">
                      <button
                        aria-label="Previous complaints"
                        disabled={offset === 0 || busy}
                        onClick={() => setOffset(Math.max(0, offset - 40))}
                      >
                        <ChevronLeft size={15} />
                      </button>
                      <span>
                        {total === null
                          ? "Reports appear after setup"
                          : total === 0
                            ? "0 reports"
                            : offset +
                              1 +
                              "–" +
                              (offset + rows.length) +
                              " of " +
                              total}
                      </span>
                      <button
                        aria-label="Next complaints"
                        disabled={
                          total === null || offset + 40 >= total || busy
                        }
                        onClick={() => setOffset(offset + 40)}
                      >
                        <ChevronRight size={15} />
                      </button>
                    </div>
                  </div>
                </div>
              </section>
              {page === "Overview" && (
                <div className="bottom-grid">
                  <section className="card status-card">
                    <div className="panel-title">
                      <Clock size={18} />
                      <h3>From reported to resolved</h3>
                    </div>
                    <p>Every report has a next step.</p>
                    <div className="status-items">
                      {Object.entries(statusLabels).map(([k, v]) => (
                        <button key={k} onClick={() => setStatus(k)}>
                          <span className={"status " + k}>
                            <i />
                            {v}
                          </span>
                          <strong>{metrics ? metrics[k] : "—"}</strong>
                        </button>
                      ))}
                    </div>
                    <div className="status-track">
                      {metrics &&
                        metrics.total > 0 &&
                        Object.keys(statusLabels).map((k) => (
                          <span
                            className={k}
                            key={k}
                            style={{
                              width: (metrics[k] / metrics.total) * 100 + "%",
                            }}
                          />
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
                      <h3>Spotted an issue on your street?</h3>
                      <p>
                        Help put it on the map. It only takes a few minutes.
                      </p>
                      <button className="text-button" onClick={report}>
                        Create a report <ArrowRight size={16} />
                      </button>
                    </div>
                  </section>
                </div>
              )}
              <footer>
                <span>
                  <span className="footer-brand">NAGARSAATHI</span> · Built for
                  better neighbourhoods.
                </span>
                <span>
                  Engineering EL · Phase 2 <span className="footer-dot">•</span>{" "}
                  Community prototype
                </span>
              </footer>
            </>
          )}
        </main>
      </div>
      {toast && (
        <div className="toast" role="status">
          <Check size={17} />
          {toast}
        </div>
      )}
      {(detail || setup) && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => e.target === e.currentTarget && close()}
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
              onClick={close}
              aria-label="Close dialog"
            >
              <X />
            </button>
            {setup ? (
              <>
                <div className="eyebrow">WORKSPACE SETUP</div>
                <h2 id="dialog-title">Connect your civic workspace</h2>
                <p>
                  The application never substitutes invented reports for a
                  database connection.
                </p>
                <ol className="setup-list">
                  <li>
                    <strong>Prepare Supabase</strong>
                    <p>
                      Run supabase/001_initial.sql and enable anonymous sign-ins
                      in Authentication.
                    </p>
                  </li>
                  <li>
                    <strong>Configure the frontend</strong>
                    <p>
                      Copy .env.example to .env and provide the Supabase project
                      URL, public anon key, and FastAPI base URL.
                    </p>
                  </li>
                  <li>
                    <strong>Start the reporting service</strong>
                    <p>
                      Configure backend-only credentials, install
                      backend/requirements.txt, and run uvicorn
                      backend.main:app.
                    </p>
                  </li>
                  <li>
                    <strong>Enable the trained model</strong>
                    <p>
                      Set YOLO_MODEL_PATH to your teammate’s YOLO11n weights.
                      Reporting works without inference.
                    </p>
                  </li>
                </ol>
                <div className="privacy-note">
                  <ShieldCheck size={20} />
                  <span>
                    Service-role keys stay on the server. Photos use a private
                    bucket and temporary access links.
                  </span>
                </div>
              </>
            ) : (
              <>
                <div className="eyebrow">COMPLAINT DETAILS</div>
                <h2 id="dialog-title">{detail.reference || `Report #${detail.id}`}</h2>
                <div className="button-row">
                  <span className={"badge " + detail.issue_type}>
                    {issueLabels[detail.issue_type] || "Issue"}
                  </span>
                  <span className={"status " + (detail.status || "open")}>
                    <i />
                    {statusLabels[detail.status] || detail.status || "Open"}
                  </span>
                  {detail.priority && (
                    <span className={"status " + detail.priority} style={{ marginLeft: "6px" }}>
                      Priority: {detail.priority.toUpperCase()}
                    </span>
                  )}
                </div>
                <p className="review-description">{detail.description}</p>
                {detail.photo_url && (
                  <img
                    className="detail-photo"
                    src={
                      detail.photo_url.startsWith("http")
                        ? detail.photo_url
                        : `http://127.0.0.1:8001${detail.photo_url}?token=${getStoredToken()}`
                    }
                    alt="Complaint photo"
                  />
                )}
                <p className="location-line">
                  <MapPin size={17} />
                  {detail.latitude?.toFixed(6)}, {detail.longitude?.toFixed(6)}
                </p>
                {detail.landmark && <p>{detail.landmark}</p>}
                {detail.duplicate_of && (
                  <div className="privacy-note" style={{ margin: "10px 0" }}>
                    <Info size={16} />
                    <span>Advisory link: Possible duplicate of Report #{detail.duplicate_of}</span>
                  </div>
                )}
                <dl>
                  <dt>Submitted</dt>
                  <dd>
                    {new Date(
                      typeof detail.created_at === "number" && detail.created_at < 1e11
                        ? detail.created_at * 1000
                        : detail.created_at
                    ).toLocaleString()}
                  </dd>
                  {detail.priority_reason && (
                    <>
                      <dt>Review note</dt>
                      <dd>{detail.priority_reason}</dd>
                    </>
                  )}
                </dl>
                {detail.analysis ? (
                  <div className="ai-panel">
                    <strong>YOLO11n Detection Findings</strong>
                    <p>
                      {detail.analysis?.detections?.length || 0} issues detected · {detail.analysis?.model_version || "YOLO11n"}
                    </p>
                    {detail.analysis?.detections?.length === 0 && (
                      <p className="muted">No road issues detected in photo.</p>
                    )}
                    {detail.analysis?.detections?.map((d, i) => (
                      <p key={i}>
                        {(d.label || d.class_name || "Issue").replace(/^./, (c) => c.toUpperCase())} · {Math.round(d.confidence * 100)}% model confidence
                      </p>
                    ))}
                    <small>
                      AI assists review and may miss or misidentify issues.
                    </small>
                  </div>
                ) : (
                  <p className="muted">
                    AI analysis:{" "}
                    {detail.analysis_status === "failed"
                      ? "Analysis failed"
                      : detail.analysis_status === "unavailable"
                        ? "Model unavailable"
                        : "Not requested"}
                  </p>
                )}

                {user?.role === "admin" && (
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
                      <span>ADMINISTRATOR REVIEW</span>
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
                            setReviewForm({
                              ...reviewForm,
                              status: e.target.value,
                            })
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
                            setReviewForm({
                              ...reviewForm,
                              priority: e.target.value,
                            })
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
                        Priority Reason (Required)
                      </label>
                      <input
                        type="text"
                        placeholder="Explain priority reason"
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
                    <button
                      className="primary"
                      style={{
                        width: "100%",
                        padding: "10px",
                        justifyContent: "center",
                      }}
                      disabled={reviewSaving || !reviewForm.priority_reason.trim()}
                      onClick={handleSaveReview}
                    >
                      {reviewSaving ? "Saving review..." : "Save Admin Review"}
                    </button>
                  </div>
                )}

                <div className="detail-actions">
                  <button
                    className="primary"
                    onClick={() => {
                      changePage("Complaint Map");
                      setSelected(detail);
                      close();
                    }}
                  >
                    <Map size={16} />
                    Show on map
                  </button>
                  <button
                    className="secondary"
                    onClick={() =>
                      navigator.clipboard
                        .writeText(String(detail.reference || detail.id))
                        .then(() => notify("Reference copied"))
                        .catch(() => notify("Clipboard unavailable"))
                    }
                  >
                    <Copy size={16} />
                    Copy reference
                  </button>
                  <button
                    className="secondary"
                    onClick={() =>
                      navigator.clipboard
                        .writeText(
                          location.origin +
                            location.pathname +
                            "#/complaints/" +
                            detail.id,
                        )
                        .then(() => notify("Details link copied"))
                        .catch(() => notify("Clipboard unavailable"))
                    }
                  >
                    <ExternalLink size={16} />
                    Copy details link
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      )}

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
            <h2 id="auth-title">
              {authTab === "login" ? "Sign In to NAGARSAATHI" : "Register Citizen Account"}
            </h2>
            <p style={{ fontSize: "13px", color: "#64748b", marginBottom: "16px" }}>
              {authTab === "login"
                ? "Access your submitted complaints, track civic resolution, and manage road issues."
                : "Create a verified citizen account. Public registration always creates a citizen account."}
            </p>

            <div style={{ display: "flex", borderBottom: "1px solid #e2e8f0", marginBottom: "20px" }}>
              <button
                type="button"
                className="text-button"
                style={{
                  flex: 1,
                  padding: "10px",
                  borderBottom: authTab === "login" ? "2px solid #0d9488" : "none",
                  fontWeight: authTab === "login" ? 700 : 500,
                  color: authTab === "login" ? "#0d9488" : "#64748b",
                }}
                onClick={() => {
                  setAuthTab("login");
                  setAuthError("");
                }}
              >
                Sign In
              </button>
              <button
                type="button"
                className="text-button"
                style={{
                  flex: 1,
                  padding: "10px",
                  borderBottom: authTab === "register" ? "2px solid #0d9488" : "none",
                  fontWeight: authTab === "register" ? 700 : 500,
                  color: authTab === "register" ? "#0d9488" : "#64748b",
                }}
                onClick={() => {
                  setAuthTab("register");
                  setAuthError("");
                }}
              >
                Register
              </button>
            </div>

            {authError && (
              <div className="error-box" style={{ margin: "0 0 16px 0" }}>
                {authError}
              </div>
            )}

            <form onSubmit={authTab === "login" ? handleLogin : handleRegister}>
              {authTab === "register" && (
                <div style={{ marginBottom: "14px" }}>
                  <label className="field-label" htmlFor="reg-name">
                    Full Name <span>*</span>
                  </label>
                  <input
                    id="reg-name"
                    type="text"
                    required
                    placeholder="e.g. John Citizen"
                    value={authForm.name}
                    onChange={(e) => setAuthForm({ ...authForm, name: e.target.value })}
                    style={{ width: "100%", padding: "10px", borderRadius: "6px", border: "1px solid #cbd5e1" }}
                  />
                </div>
              )}

              <div style={{ marginBottom: "14px" }}>
                <label className="field-label" htmlFor="auth-email">
                  Email Address <span>*</span>
                </label>
                <input
                  id="auth-email"
                  type="email"
                  required
                  placeholder="citizen@example.com"
                  value={authForm.email}
                  onChange={(e) => setAuthForm({ ...authForm, email: e.target.value })}
                  style={{ width: "100%", padding: "10px", borderRadius: "6px", border: "1px solid #cbd5e1" }}
                />
              </div>

              <div style={{ marginBottom: "20px" }}>
                <label className="field-label" htmlFor="auth-pass">
                  Password <span>*</span>
                </label>
                <input
                  id="auth-pass"
                  type="password"
                  required
                  minLength={authTab === "register" ? 10 : 1}
                  placeholder={authTab === "register" ? "At least 10 characters" : "Password"}
                  value={authForm.password}
                  onChange={(e) => setAuthForm({ ...authForm, password: e.target.value })}
                  style={{ width: "100%", padding: "10px", borderRadius: "6px", border: "1px solid #cbd5e1" }}
                />
                {authTab === "register" && (
                  <small style={{ color: "#64748b", fontSize: "11px", display: "block", marginTop: "4px" }}>
                    Must contain 10–128 characters.
                  </small>
                )}
              </div>

              <button
                type="submit"
                className="primary"
                style={{ width: "100%", padding: "12px", justifyContent: "center" }}
                disabled={authLoading}
              >
                {authLoading ? "Please wait..." : authTab === "login" ? "Sign In" : "Create Citizen Account"}
              </button>
            </form>

            <div style={{ marginTop: "24px", paddingTop: "16px", borderTop: "1px solid #f1f5f9" }}>
              <div style={{ fontSize: "11px", color: "#64748b", marginBottom: "8px", fontWeight: 600 }}>
                QUICK TEST ACCOUNTS:
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  type="button"
                  className="secondary"
                  style={{ flex: 1, fontSize: "12px", padding: "8px" }}
                  onClick={() => handleLogin(null, "citizen1@example.com", "securepassword123")}
                >
                  👤 Demo Citizen
                </button>
                <button
                  type="button"
                  className="secondary"
                  style={{ flex: 1, fontSize: "12px", padding: "8px", color: "#b45309" }}
                  onClick={() => handleLogin(null, "admin@nagarsaathi.org", "adminpassword123")}
                >
                  🛡️ Demo Admin
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
