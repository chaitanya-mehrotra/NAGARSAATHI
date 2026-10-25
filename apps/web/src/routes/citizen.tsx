import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router";
import { z } from "zod";
import {
  api,
  getJson,
  type PublicConfig,
  type ReportDetail,
  type ReportPage,
  type UploadReceipt,
  type IssueSummary,
} from "../api/client";
import { PinMap } from "../components/PinMap";
import { SignIn, useSession } from "../session";

type Fields = {
  description: string;
  claimed_category: string;
  address_text: string;
  longitude: string;
  latitude: string;
  confirmed: boolean;
  suggested_issue_id?: string;
  reported_hazard?: boolean;
};
type Saved = { fields: Fields; uploads: UploadReceipt[]; key: string };
const initial: Fields = {
  description: "",
  claimed_category: "pothole",
  address_text: "",
  longitude: "77.645",
  latitude: "12.93",
  confirmed: false,
};
const details = z.object({
  description: z
    .string()
    .trim()
    .min(5, "Describe the problem in at least five characters")
    .max(2000),
  claimed_category: z.string().min(1),
  address_text: z.string().max(500),
  longitude: z.coerce.number().min(-180).max(180),
  latitude: z.coerce.number().min(-90).max(90),
  confirmed: z.literal(true, {
    error: "Confirm the issue position before continuing",
  }),
});

export function NewReport() {
  const { actor, token } = useSession();
  if (!actor) return <SignIn />;
  if (!actor.grants.some((grant) => grant.role === "citizen"))
    return (
      <section className="panel">
        <h1>Citizen access required</h1>
      </section>
    );
  return <ReportForm key={actor.id} token={token} identity={actor.id} />;
}

function ReportForm({ token, identity }: { token: string; identity: string }) {
  const draftKey = `draft-${identity}`;
  const submitted = useRef(false);
  const saved = useRef<Saved | null>(
    (() => {
      try {
        return JSON.parse(sessionStorage.getItem(draftKey) || "null");
      } catch {
        return null;
      }
    })(),
  );
  const {
    register,
    watch,
    setValue,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<Fields>({ defaultValues: saved.current?.fields || initial });
  const fields = watch();
  const nearby = useQuery({
    queryKey: [
      "nearby",
      fields.longitude,
      fields.latitude,
      fields.claimed_category,
    ],
    enabled:
      fields.confirmed &&
      Number.isFinite(Number(fields.longitude)) &&
      Number.isFinite(Number(fields.latitude)),
    queryFn: () =>
      api<IssueSummary[]>(
        `/api/v1/issues/nearby?longitude=${encodeURIComponent(fields.longitude)}&latitude=${encodeURIComponent(fields.latitude)}&category=${encodeURIComponent(fields.claimed_category)}`,
        token,
      ),
  });
  const [files, setFiles] = useState<File[]>([]);
  const [uploads, setUploads] = useState<UploadReceipt[]>(
    saved.current?.uploads || [],
  );
  const [key, setKey] = useState(saved.current?.key || crypto.randomUUID());
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setFailure] = useState("");
  const [geoMessage, setGeoMessage] = useState("");
  const navigate = useNavigate();
  const config = useQuery({
    queryKey: ["public-config"],
    queryFn: () => getJson<PublicConfig>("/api/v1/config/public"),
  });
  const [previews, setPreviews] = useState<string[]>([]);
  useEffect(() => {
    const urls = files.map((file) => URL.createObjectURL(file));
    setPreviews(urls);
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, [files]);
  useEffect(() => {
    if (submitted.current) return;
    sessionStorage.setItem(draftKey, JSON.stringify({ fields, uploads, key }));
  }, [fields, uploads, key, draftKey]);
  function edited() {
    setReview(false);
    setKey(crypto.randomUUID());
    setFailure("");
  }
  async function prepare(values: Fields) {
    if (!values.longitude.trim() || !values.latitude.trim()) {
      setError(!values.longitude.trim() ? "longitude" : "latitude", {
        message: "Enter the issue coordinates",
      });
      return;
    }
    const parsed = details.safeParse(values);
    if (!parsed.success) {
      for (const issue of parsed.error.issues)
        setError(issue.path[0] as keyof Fields, { message: issue.message });
      return;
    }
    if (!uploads.length && !files.length) {
      setFailure("Choose at least one photo.");
      return;
    }
    setBusy(true);
    setFailure("");
    try {
      let ready = uploads.filter(
        (item) => new Date(item.expires_at) > new Date(),
      );
      // Successfully uploaded files are removed one by one; a failed file stays retryable.
      const remaining = [...files];
      while (remaining.length) {
        const file = remaining[0];
        const receipt = await api<UploadReceipt>("/api/v1/uploads", token, {
          method: "POST",
          body: file,
          headers: { "Content-Type": file.type },
        });
        const complete = await api<UploadReceipt>(
          `/api/v1/uploads/${receipt.id}/complete`,
          token,
          { method: "POST" },
        );
        ready = [...ready, complete];
        setUploads(ready);
        remaining.shift();
        setFiles([...remaining]);
      }
      if (!ready.length)
        throw new Error("Uploads expired. Choose the photos again.");
      setUploads(ready);
      setReview(true);
    } catch (failure) {
      setFailure(
        failure instanceof Error
          ? failure.message
          : "Upload failed. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function submit() {
    if (busy) return;
    setBusy(true);
    setFailure("");
    const payload = {
      description: fields.description,
      claimed_category: fields.claimed_category,
      address_text: fields.address_text || null,
      reported_hazard: !!fields.reported_hazard,
      suggested_issue_id: nearby.data?.some(
        (i) => i.id === fields.suggested_issue_id,
      )
        ? fields.suggested_issue_id
        : null,
      media_ids: uploads.map((item) => item.id),
      location_source: "confirmed_pin",
      location: {
        longitude: Number(fields.longitude),
        latitude: Number(fields.latitude),
        confirmed: fields.confirmed,
      },
    };
    try {
      const report = await api<ReportDetail>("/api/v1/reports", token, {
        method: "POST",
        body: JSON.stringify(payload),
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      });
      submitted.current = true;
      sessionStorage.removeItem(draftKey);
      navigate(`/reports/${report.id}?receipt=1`);
    } catch (failure) {
      setFailure(
        failure instanceof Error
          ? failure.message
          : "Submission failed. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  function locate() {
    if (!navigator.geolocation) {
      setGeoMessage("Location unavailable. Enter the issue coordinates.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        edited();
        setValue("longitude", String(position.coords.longitude));
        setValue("latitude", String(position.coords.latitude));
        setValue("confirmed", false);
        setGeoMessage(
          "Check the pin: your position may differ from the photographed issue.",
        );
      },
      () =>
        setGeoMessage(
          "Location permission denied or unavailable. Enter coordinates or use the map.",
        ),
      { timeout: 5000, enableHighAccuracy: true },
    );
  }
  return (
    <section className="panel">
      <p className="eyebrow">CITIZEN REPORT</p>
      <h1>Report a problem</h1>
      <p>
        One problem, one location. Photos await review; this is a local demo.
      </p>
      <form onSubmit={handleSubmit(prepare)} onChange={edited}>
        <fieldset disabled={busy || review}>
          <legend>1. Evidence and description</legend>
          <label htmlFor="photos">Photos (JPEG or PNG, up to 3)</label>
          <input
            id="photos"
            type="file"
            accept="image/jpeg,image/png"
            multiple
            onChange={(e) => {
              const selected = Array.from(e.target.files || []);
              if (selected.length + uploads.length > 3) {
                setFailure("Use at most three photos.");
                return;
              }
              setFiles(selected);
              edited();
            }}
          />
          <div className="photo-grid">
            {previews.map((url, index) => (
              <figure key={url}>
                <img src={url} alt={`Selected photo ${index + 1}`} />
                <figcaption>{files[index]?.name}</figcaption>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setFiles(files.filter((_, i) => i !== index));
                    edited();
                  }}
                >
                  Remove photo {index + 1}
                </button>
              </figure>
            ))}
          </div>
          {uploads.map((item, index) => (
            <p key={item.id}>
              Photo {index + 1} uploaded ({item.width} × {item.height})
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setUploads(uploads.filter((x) => x.id !== item.id));
                  edited();
                }}
              >
                Remove uploaded photo {index + 1}
              </button>
            </p>
          ))}
          <label htmlFor="description">Describe the problem</label>
          <textarea
            id="description"
            {...register("description")}
            aria-invalid={!!errors.description}
            aria-describedby={
              errors.description ? "description-error" : undefined
            }
            rows={4}
          />
          {errors.description && (
            <p id="description-error" role="alert">
              {errors.description.message}
            </p>
          )}
          <label className="checkbox">
            <input type="checkbox" {...register("reported_hazard")} /> I believe
            this poses an immediate hazard
          </label>
          <p className="hint">
            This flags the report for staff attention; it is not a confirmed
            urgency assessment.
          </p>
          <label htmlFor="category">Claimed category</label>
          <select id="category" {...register("claimed_category")}>
            {config.data?.categories.map((item) => (
              <option key={item.code} value={item.code}>
                {item.label}
              </option>
            ))}
          </select>
          {config.isError && (
            <p role="alert">
              Categories unavailable.{" "}
              <button type="button" onClick={() => void config.refetch()}>
                Retry categories
              </button>
            </p>
          )}
        </fieldset>
        <fieldset disabled={busy || review}>
          <legend>2. Confirm the issue position</legend>
          <PinMap
            longitude={
              Number.isFinite(Number(fields.longitude)) &&
              Math.abs(Number(fields.longitude)) <= 180
                ? Number(fields.longitude)
                : 77.645
            }
            latitude={
              Number.isFinite(Number(fields.latitude)) &&
              Math.abs(Number(fields.latitude)) <= 90
                ? Number(fields.latitude)
                : 12.93
            }
            onPin={(lon, lat) => {
              if (review || busy) return;
              edited();
              setValue("longitude", lon.toFixed(6));
              setValue("latitude", lat.toFixed(6));
              setValue("confirmed", false);
            }}
          />
          <button type="button" className="secondary" onClick={locate}>
            Use my location
          </button>
          {geoMessage && <p role="status">{geoMessage}</p>}
          <div className="form-grid">
            <div>
              <label htmlFor="longitude">Longitude</label>
              <input
                id="longitude"
                type="number"
                step="any"
                {...register("longitude", {
                  onChange: () => setValue("confirmed", false),
                })}
                aria-invalid={!!errors.longitude}
              />
              {errors.longitude && (
                <p role="alert">{errors.longitude.message}</p>
              )}
            </div>
            <div>
              <label htmlFor="latitude">Latitude</label>
              <input
                id="latitude"
                type="number"
                step="any"
                {...register("latitude", {
                  onChange: () => setValue("confirmed", false),
                })}
                aria-invalid={!!errors.latitude}
              />
              {errors.latitude && <p role="alert">{errors.latitude.message}</p>}
            </div>
          </div>
          <label htmlFor="address">Address or landmark (optional)</label>
          <input id="address" {...register("address_text")} />
          <p className="hint">
            Address lookup is unavailable in this demo. A landmark helps
            reviewers; coordinates determine coverage.
          </p>
          <label className="checkbox">
            <input
              type="checkbox"
              {...register("confirmed")}
              aria-invalid={!!errors.confirmed}
            />
            I confirm this pin marks the issue, not just the camera position.
          </label>
          {errors.confirmed && <p role="alert">{errors.confirmed.message}</p>}
          {fields.confirmed && (
            <>
              <label htmlFor="suggested-issue">
                Does this look like an existing nearby issue?
              </label>
              <select id="suggested-issue" {...register("suggested_issue_id")}>
                <option value="">New problem or unsure</option>
                {nearby.data?.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.public_reference} · {i.category.replaceAll("_", " ")} ·{" "}
                    {i.status}
                  </option>
                ))}
              </select>
              <p className="hint">
                This is a suggestion. Staff compare the evidence before linking
                your report.
              </p>
              {nearby.isError && (
                <p>Nearby issue lookup is unavailable. You can still submit.</p>
              )}
            </>
          )}
        </fieldset>
        {!review && (
          <button type="submit" disabled={busy || config.isPending}>
            {busy ? "Uploading photos…" : "Review report"}
          </button>
        )}
      </form>
      {review && (
        <section className="review">
          <h2>Review before submitting</h2>
          <p>{fields.description}</p>
          <dl>
            <dt>Claimed category</dt>
            <dd>
              {
                config.data?.categories.find(
                  (c) => c.code === fields.claimed_category,
                )?.label
              }
            </dd>
            <dt>Issue pin</dt>
            <dd>
              {fields.latitude}, {fields.longitude}
            </dd>
            <dt>Photos</dt>
            <dd>{uploads.length}</dd>
          </dl>
          <p>
            Validation and repair updates will follow staff review. No
            resolution estimate is promised.
          </p>
          <div className="actions">
            <button disabled={busy} onClick={() => void submit()}>
              {busy ? "Submitting…" : "Submit report"}
            </button>
            <button
              disabled={busy}
              className="secondary"
              onClick={() => setReview(false)}
            >
              Edit report
            </button>
          </div>
        </section>
      )}
      {error && (
        <p role="alert">{error} Your draft is preserved; retry when ready.</p>
      )}
      <p className="hint">
        Draft metadata and completed uploads remain in this browser tab. After
        reload, reselect any photos whose upload failed.
      </p>
    </section>
  );
}

export function PrivatePhoto({ url, alt }: { url: string; alt: string }) {
  const { token } = useSession();
  const [src, setSrc] = useState("");
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    let object = "";
    setSrc("");
    setFailed(false);
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => {
        if (!response.ok) throw new Error("Photo unavailable");
        return response.blob();
      })
      .then((blob) => {
        if (active) {
          object = URL.createObjectURL(blob);
          setSrc(object);
        }
      })
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
      if (object) URL.revokeObjectURL(object);
    };
  }, [url, token, retry]);
  return src ? (
    <img src={src} alt={alt} />
  ) : failed ? (
    <p role="alert">
      Photo unavailable.{" "}
      <button onClick={() => setRetry(retry + 1)}>Retry photo</button>
    </p>
  ) : (
    <p role="status">Loading photo…</p>
  );
}

export function ReportView() {
  const { actor, token } = useSession();
  const { id } = useParams();
  const report = useQuery({
    queryKey: ["report", actor?.id, id],
    enabled: !!actor,
    queryFn: () => api<ReportDetail>(`/api/v1/reports/${id}`, token),
  });
  if (!actor) return <SignIn />;
  return (
    <section className="panel">
      <h1>
        {new URLSearchParams(location.search).has("receipt")
          ? "Report received"
          : "Report details"}
      </h1>
      {report.isPending && <p role="status">Loading report…</p>}
      {report.isError && (
        <p role="alert">
          {report.error.message}{" "}
          <button onClick={() => void report.refetch()}>Retry report</button>
        </p>
      )}
      {report.data && (
        <>
          <p className="tracking">{report.data.public_reference}</p>
          <p className="status">{report.data.state.replaceAll("_", " ")}</p>
          <p>
            Validation: {report.data.validation_status || "pending"}.{" "}
            {report.data.review_reason}
          </p>
          <p>{report.data.description}</p>
          {report.data.issue_reference && (
            <p className="notice">
              {report.data.link_method === "reviewed_duplicate" ||
              report.data.link_method === "asset_match"
                ? "Your report is part of an existing issue."
                : "Your report has been accepted as a shared issue."}{" "}
              Tracking issue: {report.data.issue_reference} ·{" "}
              {report.data.issue_status?.replaceAll("_", " ")}.
            </p>
          )}
          <dl>
            <dt>Claimed category</dt>
            <dd>{report.data.claimed_category.replaceAll("_", " ")}</dd>
            <dt>Accepted category</dt>
            <dd>{report.data.canonical_category || "Awaiting validation"}</dd>
            <dt>Area</dt>
            <dd>
              {report.data.area_code?.replaceAll("_", " ") ||
                "Awaiting location review / outside pilot"}
            </dd>
            <dt>Received</dt>
            <dd>
              {new Date(report.data.received_at).toLocaleString("en-IN", {
                timeZone: "Asia/Kolkata",
              })}
            </dd>
          </dl>
          <p>{report.data.address_text || "No address supplied"}</p>
          <div className="photo-grid">
            {report.data.media.map((media, index) => (
              <PrivatePhoto
                key={media.id}
                url={media.content_url}
                alt={`Submitted evidence ${index + 1}`}
              />
            ))}
          </div>
        </>
      )}
      <Link to="/reports">My reports</Link>
    </section>
  );
}

export function MyReports() {
  const { actor, token } = useSession();
  const [cursor, setCursor] = useState<string | null>(null);
  const reports = useQuery({
    queryKey: ["mine", actor?.id, cursor],
    enabled: !!actor,
    queryFn: () =>
      api<ReportPage>(
        `/api/v1/reports/mine${cursor ? `?cursor=${cursor}` : ""}`,
        token,
      ),
  });
  if (!actor) return <SignIn />;
  return (
    <section className="panel">
      <h1>My reports</h1>
      <Link className="button" to="/report/new">
        Report a problem
      </Link>
      {reports.isPending && <p role="status">Loading your reports…</p>}
      {reports.isError && (
        <p role="alert">
          {reports.error.message}{" "}
          <button onClick={() => void reports.refetch()}>Retry reports</button>
        </p>
      )}
      {reports.data?.items.length === 0 && <p>No reports yet.</p>}
      <ul className="report-list">
        {reports.data?.items.map((item) => (
          <li key={item.id}>
            <Link to={`/reports/${item.id}`}>
              <strong>{item.description}</strong>
              <span>
                {item.state.replaceAll("_", " ")} ·{" "}
                {item.area_code?.replaceAll("_", " ") || "Location review"}
              </span>
              <small>{item.public_reference}</small>
            </Link>
          </li>
        ))}
      </ul>
      {reports.data?.next_cursor && (
        <button onClick={() => setCursor(reports.data?.next_cursor || null)}>
          Older reports
        </button>
      )}
      {cursor && (
        <button className="secondary" onClick={() => setCursor(null)}>
          Newest reports
        </button>
      )}
    </section>
  );
}
