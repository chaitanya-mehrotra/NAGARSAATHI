import { useQuery } from "@tanstack/react-query";
import { Link, Route, Routes } from "react-router";
import { getJson, type PublicConfig } from "./api/client";
import { copy } from "./i18n/en";
import { SessionProvider, useSession } from "./session";
import { MyReports, NewReport, ReportView } from "./routes/citizen";
import { ReviewDetail, ReviewInbox } from "./routes/reviews";
import { Duplicates, Issues, SharedIssue } from "./routes/issues";
import { PriorityQueue, PriorityPolicies } from "./routes/priority";
import { StaffQueue, AreaOverview } from "./routes/staff";
import { WorkTasks, WorkView } from "./routes/work";

function Home() {
  const config = useQuery({
    queryKey: ["public-config"],
    queryFn: ({ signal }) =>
      getJson<PublicConfig>("/api/v1/config/public", signal),
  });
  return (
    <>
      <section className="hero" aria-labelledby="home-title">
        <p className="eyebrow">FOR OUR STREETS. FOR OUR NEIGHBOURS.</p>
        <h1 id="home-title">{copy.title}</h1>
        <p className="intro">{copy.intro}</p>
        <div className="notice">{copy.disclaimer}</div>
        <div className="actions">
          <Link className="button" to="/report/new">
            Report a problem
          </Link>
          <Link className="button secondary" to="/reports">
            My reports
          </Link>
        </div>
      </section>
      <div className="content-grid">
        <section className="coverage" aria-labelledby="coverage-title">
          <p className="eyebrow">PROPOSED PILOT</p>
          <h2 id="coverage-title">{copy.coverage}</h2>
          <p>{copy.coverageNote}</p>
          {config.data && (
            <ul className="areas">
              {config.data.pilot.service_areas.map((area) => (
                <li key={area}>{area}</li>
              ))}
            </ul>
          )}
        </section>
        <section aria-labelledby="category-title">
          <h2 id="category-title">{copy.categories}</h2>
          {config.isPending && <p role="status">Loading pilot details…</p>}
          {config.isError && (
            <div role="alert">
              <p>{copy.unavailable}</p>
              <button onClick={() => void config.refetch()}>
                {copy.retry}
              </button>
            </div>
          )}
          {config.data && (
            <ul className="category-list">
              {config.data.categories.map((category, index) => (
                <li key={category.code}>
                  <span className="category-number">0{index + 1}</span>
                  <span>{category.label}</span>
                  {category.requires_manual_categorisation && (
                    <small>Staff review</small>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <section className="build-note">
        <h2>What is available now</h2>
        <p>
          Submit photos and a confirmed issue pin, then track your report.
          Reports await validation; this demo does not promise a repair or
          municipal handoff.
        </p>
      </section>
    </>
  );
}

export function App() {
  return (
    <SessionProvider>
      <Application />
    </SessionProvider>
  );
}

function Application() {
  const { actor, setToken } = useSession();
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header>
        <Link to="/" className="brand">
          NAGAR<span>SAATHI</span>
        </Link>
        <span className="demo-badge">{copy.demo}</span>
        <nav aria-label="Main">
          {actor?.grants.some((grant) =>
            ["reviewer", "admin"].includes(grant.role),
          ) && (
            <>
              <Link to="/reviews">Review inbox</Link>
              <Link to="/reviews/duplicates">Duplicates</Link>
              <Link to="/issues">Shared issues</Link>
              <Link to="/staff">Work queue</Link>
              <Link to="/staff/areas">Service areas</Link>
              <Link to="/priority">Priority review</Link>
              {actor.grants.some((g) => g.role === "admin" && !g.area_id) && (
                <Link to="/priority/policies">Priority policies</Link>
              )}
            </>
          )}
          <Link to="/report/new">Report</Link>
          {actor?.grants.some((g) => g.role === "operator") && (
            <Link to="/work">My work tasks</Link>
          )}
          <Link to="/reports">My reports</Link>
          {actor && (
            <button className="secondary" onClick={() => setToken("")}>
              Sign out
            </button>
          )}
        </nav>
      </header>
      <main id="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/report/new" element={<NewReport />} />
          <Route path="/reports" element={<MyReports />} />
          <Route path="/reports/:id" element={<ReportView />} />
          <Route path="/reviews" element={<ReviewInbox />} />
          <Route path="/reviews/duplicates" element={<Duplicates />} />
          <Route path="/issues" element={<Issues />} />
          <Route path="/staff" element={<StaffQueue />} />
          <Route path="/work" element={<WorkTasks />} />
          <Route path="/work/:id" element={<WorkView />} />
          <Route path="/staff/areas" element={<AreaOverview />} />
          <Route path="/issues/:id" element={<SharedIssue />} />
          <Route path="/priority" element={<PriorityQueue />} />
          <Route path="/priority/policies" element={<PriorityPolicies />} />
          <Route path="/reviews/:id" element={<ReviewDetail />} />
          <Route
            path="*"
            element={
              <section className="hero">
                <h1>Page not found</h1>
                <Link to="/">Return home</Link>
              </section>
            }
          />
        </Routes>
      </main>
      <footer>
        Local civic complaint pilot · Bengaluru · Demo configuration
      </footer>
    </>
  );
}
