import { FormEvent, ReactNode, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { ApiError, User, api, localInputToIso, setToken, token } from "./api";
import { categoryLabel, statusLabel, unitLabel, when } from "./format";

type NextAction = { label: string; href: string };
type Batch = {
  id: number;
  category: string;
  quantity: number;
  remaining_quantity: number;
  unit: string;
  storage_requirement: string;
  distribution_deadline: string;
  note: string | null;
};
type Need = { category: string; quantity: number; unit: string };
type Site = {
  id: number;
  name: string;
  address: string;
  area: string;
  active: boolean;
  last_submitted_at: string | null;
  fresh: boolean;
  unavailable: boolean;
  receiving_start: string | null;
  receiving_end: string | null;
  storage: string[];
  needs: Need[];
};
type Allocation = {
  id: number;
  batch_id: number;
  site_id: number;
  site_name: string;
  category: string;
  unit: string;
  quantity: number;
  quantity_label: string;
  status: string;
  explanation: string | null;
  warning: string | null;
  events: { from_status: string | null; to_status: string; quantity: number; note: string | null; created_at: string }[];
};
type Recommendation = {
  batch: Batch;
  proposals: {
    site_id: number;
    site_name: string;
    suggested_quantity: number;
    explanation: string;
    room: number;
  }[];
  excluded: { site_id: number; site_name: string; reasons: string[] }[];
};

function useUser() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(!token());
  useEffect(() => {
    if (!token()) return;
    api<User>("/api/auth/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setReady(true));
  }, []);
  return { user, ready, setUser };
}

function Banner() {
  return (
    <p className="banner">
      Practice data. These sites are invented and are not partners of a food rescue organization.
    </p>
  );
}

function Shell({ user, onSignOut, children }: { user: User; onSignOut: () => void; children: ReactNode }) {
  return (
    <>
      <header className="top">
        <Link to="/" className="brand">Pantry Desk</Link>
        <nav>
          <Link to="/">Overview</Link>
          <Link to="/sites">Sites</Link>
          <Link to="/batches">Food</Link>
          <Link to="/allocations">Deliveries</Link>
        </nav>
        <div className="who">
          <span>{user.full_name}</span>
          <button type="button" onClick={onSignOut}>Sign out</button>
        </div>
      </header>
      <Banner />
      <main className="page">{children}</main>
    </>
  );
}

function Notice({ error, empty }: { error?: string; empty?: string }) {
  if (error) return <p className="message error" role="alert">{error}</p>;
  if (empty) return <p className="message">{empty}</p>;
  return null;
}

export function Login({ onSignedIn }: { onSignedIn: (user: User) => void }) {
  const [email, setEmail] = useState("coordinator@pantrydesk.example");
  const [password, setPassword] = useState("pantry-demo");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const result = await api<{ access_token: string; user: User }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(result.access_token);
      onSignedIn(result.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="login">
      <p className="eyebrow">Practice data only</p>
      <h1>Pantry Desk</h1>
      <p className="lede">Sign in to record what sites can receive, then reserve a food batch against those reports.</p>
      <form onSubmit={submit} className="card form">
        <label>
          Email
          <input value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
        </label>
        {error ? <p className="message error" role="alert">{error}</p> : null}
        <button type="submit" disabled={pending}>{pending ? "Signing in…" : "Sign in"}</button>
      </form>
      <div className="demo-accounts">
        <p>Demo password: pantry-demo</p>
        <button type="button" onClick={() => setEmail("coordinator@pantrydesk.example")}>Coordinator</button>
        <button type="button" onClick={() => setEmail("elmwood@pantrydesk.example")}>Elmwood steward</button>
        <button type="button" onClick={() => setEmail("corktown@pantrydesk.example")}>Corktown steward</button>
        <button type="button" onClick={() => setEmail("riverside@pantrydesk.example")}>Riverside steward</button>
      </div>
    </main>
  );
}

function Overview() {
  const [data, setData] = useState<{
    next_action: NextAction;
    batches: Batch[];
    pending: Allocation[];
    sites_needing_updates: { id: number; name: string; reason: string }[];
  } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<NonNullable<typeof data>>("/api/overview").then(setData).catch((err: ApiError) => setError(err.message));
  }, []);
  if (error) return <Notice error={error} />;
  if (!data) return <p>Loading overview…</p>;
  return (
    <>
      <h1>Overview</h1>
      <p className="next">
        Next: <Link to={data.next_action.href}>{data.next_action.label}</Link>
      </p>
      <section>
        <h2>Food still available</h2>
        {data.batches.length === 0 ? <Notice empty="No batch has quantity left to reserve." /> : (
          <ul className="plain">
            {data.batches.map((batch) => (
              <li key={batch.id}>
                <Link to={`/batches/${batch.id}`}>{categoryLabel(batch.category)}</Link>
                {" · "}
                {unitLabel(batch.remaining_quantity, batch.unit)} available
                {" · deliver by "}
                {when(batch.distribution_deadline)}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h2>Waiting on receipt</h2>
        {data.pending.length === 0 ? <Notice empty="No reserved deliveries." /> : (
          <ul className="plain">
            {data.pending.map((row) => (
              <li key={row.id}>
                <Link to={`/allocations/${row.id}`}>{row.site_name}</Link>
                {" · "}
                {row.quantity_label}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h2>Sites that need an update</h2>
        {data.sites_needing_updates.length === 0 ? <Notice empty="Every visible site has a fresh report." /> : (
          <ul className="plain">
            {data.sites_needing_updates.map((site) => (
              <li key={site.id}>
                <Link to={`/sites/${site.id}`}>{site.name}</Link>
                {" · "}
                {site.reason}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function Sites() {
  const [query, setQuery] = useState("");
  const [sites, setSites] = useState<Site[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const handle = window.setTimeout(() => {
      api<Site[]>(`/api/sites?q=${encodeURIComponent(query)}`)
        .then(setSites)
        .catch((err: ApiError) => setError(err.message));
    }, 150);
    return () => window.clearTimeout(handle);
  }, [query]);
  return (
    <>
      <h1>Sites</h1>
      <label className="search">
        Search
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Name or address" />
      </label>
      {error ? <Notice error={error} /> : null}
      {!sites ? <p>Loading sites…</p> : sites.length === 0 ? <Notice empty="No sites match that search." /> : (
        <table>
          <caption>Sites in the practice network</caption>
          <thead>
            <tr>
              <th>Site</th>
              <th>Last confirmed</th>
              <th>Can receive</th>
            </tr>
          </thead>
          <tbody>
            {sites.map((site) => (
              <tr key={site.id}>
                <td>
                  <Link to={`/sites/${site.id}`}>{site.name}</Link>
                  <div className="muted">{site.address}</div>
                </td>
                <td>{site.fresh ? when(site.last_submitted_at) : site.last_submitted_at ? `${when(site.last_submitted_at)} · stale` : "Missing"}</td>
                <td>{site.needs.map((need) => unitLabel(need.quantity, need.unit) + " " + categoryLabel(need.category).toLowerCase()).join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function SiteForm() {
  const { siteId } = useParams();
  const [site, setSite] = useState<Site | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [unavailable, setUnavailable] = useState(false);
  const [storage, setStorage] = useState<string[]>(["refrigerated"]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [lines, setLines] = useState([{ category: "produce", quantity: "0", unit: "crate" }]);

  useEffect(() => {
    api<Site>(`/api/sites/${siteId}`).then(setSite).catch((err: ApiError) => setError(err.message));
  }, [siteId]);

  function toggleStorage(kind: string) {
    setStorage((current) => current.includes(kind) ? current.filter((item) => item !== kind) : [...current, kind]);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSaved("");
    try {
      await api(`/api/sites/${siteId}/reports`, {
        method: "POST",
        body: JSON.stringify({
          receiving_start: localInputToIso(start),
          receiving_end: localInputToIso(end),
          unavailable,
          storage,
          lines: lines.map((line) => ({ ...line, quantity: Number(line.quantity) })),
        }),
      });
      setSaved("Report saved. Older reservations are unchanged.");
      const fresh = await api<Site>(`/api/sites/${siteId}`);
      setSite(fresh);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the report");
    }
  }

  if (error && !site) return <Notice error={error} />;
  if (!site) return <p>Loading site…</p>;
  return (
    <>
      <h1>{site.name}</h1>
      <p className="muted">{site.address} · {site.area}</p>
      <p>Last confirmed: {site.fresh ? when(site.last_submitted_at) : site.last_submitted_at ? `${when(site.last_submitted_at)} (stale)` : "No report yet"}</p>
      <form onSubmit={submit} className="card form">
        <fieldset>
          <legend>Storage on hand</legend>
          {["ambient", "refrigerated", "frozen"].map((kind) => (
            <label key={kind} className="check">
              <input type="checkbox" checked={storage.includes(kind)} onChange={() => toggleStorage(kind)} />
              {kind}
            </label>
          ))}
        </fieldset>
        <label className="check">
          <input type="checkbox" checked={unavailable} onChange={(event) => setUnavailable(event.target.checked)} />
          Temporarily unavailable
        </label>
        <label>
          Receiving starts
          <input type="datetime-local" required value={start} onChange={(event) => setStart(event.target.value)} />
        </label>
        <label>
          Receiving ends
          <input type="datetime-local" required value={end} onChange={(event) => setEnd(event.target.value)} />
        </label>
        {lines.map((line, index) => (
          <div className="row" key={index}>
            <label>
              Category
              <select value={line.category} onChange={(event) => setLines(lines.map((item, i) => i === index ? { ...item, category: event.target.value } : item))}>
                {Object.keys({ produce: 1, dairy: 1, bakery: 1, shelf_stable: 1, frozen: 1 }).map((category) => (
                  <option key={category} value={category}>{categoryLabel(category)}</option>
                ))}
              </select>
            </label>
            <label>
              Available quantity
              <input inputMode="numeric" value={line.quantity} onChange={(event) => setLines(lines.map((item, i) => i === index ? { ...item, quantity: event.target.value } : item))} />
            </label>
            <label>
              Unit
              <select value={line.unit} onChange={(event) => setLines(lines.map((item, i) => i === index ? { ...item, unit: event.target.value } : item))}>
                <option value="crate">Crate</option>
                <option value="case">Case</option>
                <option value="pound">Pound</option>
              </select>
            </label>
          </div>
        ))}
        <button type="button" className="secondary" onClick={() => setLines([...lines, { category: "produce", quantity: "0", unit: "crate" }])}>Add a line</button>
        {error ? <Notice error={error} /> : null}
        {saved ? <p className="message">{saved}</p> : null}
        <button type="submit">Save report</button>
      </form>
    </>
  );
}

function Batches({ coordinator }: { coordinator: boolean }) {
  const [batches, setBatches] = useState<Batch[] | null>(null);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("produce");
  const [quantity, setQuantity] = useState("10");
  const [unit, setUnit] = useState("crate");
  const [storage, setStorage] = useState("refrigerated");
  const [deadline, setDeadline] = useState("");

  function load() {
    api<Batch[]>("/api/batches").then(setBatches).catch((err: ApiError) => setError(err.message));
  }
  useEffect(load, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api("/api/batches", {
        method: "POST",
        body: JSON.stringify({
          category,
          quantity: Number(quantity),
          unit,
          storage_requirement: storage,
          distribution_deadline: localInputToIso(deadline),
        }),
      });
      setDeadline("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record the batch");
    }
  }

  return (
    <>
      <h1>Food batches</h1>
      {error ? <Notice error={error} /> : null}
      {!batches ? <p>Loading batches…</p> : batches.length === 0 ? <Notice empty="No food has been recorded." /> : (
        <table>
          <caption>Available food</caption>
          <thead>
            <tr>
              <th>Food</th>
              <th>Available quantity</th>
              <th>Deadline</th>
            </tr>
          </thead>
          <tbody>
            {batches.map((batch) => (
              <tr key={batch.id}>
                <td>{coordinator ? <Link to={`/batches/${batch.id}`}>{categoryLabel(batch.category)}</Link> : categoryLabel(batch.category)}</td>
                <td>{unitLabel(batch.remaining_quantity, batch.unit)} of {unitLabel(batch.quantity, batch.unit)}</td>
                <td>{when(batch.distribution_deadline)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {coordinator ? (
        <form onSubmit={submit} className="card form">
          <h2>Record a batch</h2>
          <label>
            Category
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="produce">Produce</option>
              <option value="dairy">Dairy</option>
              <option value="bakery">Bakery</option>
              <option value="shelf_stable">Shelf-stable food</option>
              <option value="frozen">Frozen food</option>
            </select>
          </label>
          <div className="row">
            <label>
              Quantity
              <input value={quantity} onChange={(event) => setQuantity(event.target.value)} />
            </label>
            <label>
              Unit
              <select value={unit} onChange={(event) => setUnit(event.target.value)}>
                <option value="crate">Crate</option>
                <option value="case">Case</option>
                <option value="pound">Pound</option>
              </select>
            </label>
            <label>
              Storage required
              <select value={storage} onChange={(event) => setStorage(event.target.value)}>
                <option value="ambient">Ambient</option>
                <option value="refrigerated">Refrigerated</option>
                <option value="frozen">Frozen</option>
              </select>
            </label>
          </div>
          <label>
            Distribution deadline
            <input type="datetime-local" required value={deadline} onChange={(event) => setDeadline(event.target.value)} />
          </label>
          <button type="submit">Save batch</button>
        </form>
      ) : null}
    </>
  );
}

function Planner() {
  const { batchId } = useParams();
  const navigate = useNavigate();
  const [plan, setPlan] = useState<Recommendation | null>(null);
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    api<Recommendation>(`/api/batches/${batchId}/recommendations`)
      .then((result) => {
        setPlan(result);
        const initial: Record<number, string> = {};
        result.proposals.forEach((row) => {
          initial[row.site_id] = String(row.suggested_quantity);
        });
        setQuantities(initial);
      })
      .catch((err: ApiError) => setError(err.message));
  }, [batchId]);

  async function reserveFood(event: FormEvent) {
    event.preventDefault();
    if (!plan) return;
    const lines = plan.proposals
      .map((row) => ({ site_id: row.site_id, quantity: Number(quantities[row.site_id] || 0) }))
      .filter((line) => line.quantity > 0);
    setPending(true);
    setError("");
    try {
      const created = await api<Allocation[]>(`/api/batches/${batchId}/reserve`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ lines }),
      });
      if (created[0]) navigate(`/allocations/${created[0].id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reserve the food");
    } finally {
      setPending(false);
    }
  }

  if (error && !plan) return <Notice error={error} />;
  if (!plan) return <p>Loading suggestions…</p>;
  return (
    <>
      <h1>{categoryLabel(plan.batch.category)}</h1>
      <p>{unitLabel(plan.batch.remaining_quantity, plan.batch.unit)} available. Deliver by {when(plan.batch.distribution_deadline)}.</p>
      <form onSubmit={reserveFood}>
        {plan.proposals.length === 0 ? <Notice empty="No site is eligible for this batch." /> : (
          <table>
            <caption>Suggested sites</caption>
            <thead>
              <tr>
                <th>Site</th>
                <th>Why</th>
                <th>Quantity</th>
              </tr>
            </thead>
            <tbody>
              {plan.proposals.map((row) => (
                <tr key={row.site_id}>
                  <td>{row.site_name}</td>
                  <td>{row.explanation}</td>
                  <td>
                    <label>
                      <span className="sr">Quantity for {row.site_name}</span>
                      <input
                        inputMode="numeric"
                        value={quantities[row.site_id] ?? "0"}
                        onChange={(event) => setQuantities({ ...quantities, [row.site_id]: event.target.value })}
                      />
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {plan.excluded.length > 0 ? (
          <section>
            <h2>Not suggested</h2>
            <ul className="plain">
              {plan.excluded.map((row) => (
                <li key={row.site_id}><strong>{row.site_name}.</strong> {row.reasons.join(" ")}</li>
              ))}
            </ul>
          </section>
        ) : null}
        {error ? <Notice error={error} /> : null}
        <button type="submit" disabled={pending || plan.proposals.length === 0}>{pending ? "Reserving…" : "Reserve"}</button>
      </form>
    </>
  );
}

function AllocationPage({ user }: { user: User }) {
  const { allocationId } = useParams();
  const [row, setRow] = useState<Allocation | null>(null);
  const [error, setError] = useState("");

  function load() {
    api<Allocation>(`/api/allocations/${allocationId}`).then(setRow).catch((err: ApiError) => setError(err.message));
  }
  useEffect(load, [allocationId]);

  async function act(action: "deliver" | "cancel") {
    setError("");
    try {
      const updated = await api<Allocation>(`/api/allocations/${allocationId}/${action}`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      setRow(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the delivery");
    }
  }

  if (error && !row) return <Notice error={error} />;
  if (!row) return <p>Loading delivery…</p>;
  return (
    <>
      <h1>{row.site_name}</h1>
      <p><span className={`status ${row.status}`}>{statusLabel(row.status)}</span> {row.quantity_label} of {categoryLabel(row.category).toLowerCase()}</p>
      {row.explanation ? <p>{row.explanation}</p> : null}
      {row.warning ? <p className="message" role="status">{row.warning}</p> : null}
      {error ? <Notice error={error} /> : null}
      <div className="actions">
        {row.status === "reserved" ? <button type="button" onClick={() => act("deliver")}>Confirm receipt</button> : null}
        {user.role === "coordinator" && (row.status === "reserved" || row.status === "draft") ? (
          <button type="button" className="secondary" onClick={() => act("cancel")}>Cancel reservation</button>
        ) : null}
      </div>
      <h2>History</h2>
      {row.events.length === 0 ? <Notice empty="No changes recorded." /> : (
        <ol className="plain">
          {row.events.map((event, index) => (
            <li key={index}>{when(event.created_at)} · {statusLabel(event.to_status)} · {event.note}</li>
          ))}
        </ol>
      )}
    </>
  );
}

function Deliveries() {
  const [rows, setRows] = useState<Allocation[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Allocation[]>("/api/allocations").then(setRows).catch((err: ApiError) => setError(err.message));
  }, []);
  return (
    <>
      <h1>Deliveries</h1>
      {error ? <Notice error={error} /> : null}
      {!rows ? <p>Loading deliveries…</p> : rows.length === 0 ? <Notice empty="No deliveries yet." /> : (
        <table>
          <caption>Allocations</caption>
          <thead>
            <tr>
              <th>Site</th>
              <th>Quantity</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td><Link to={`/allocations/${row.id}`}>{row.site_name}</Link></td>
                <td>{row.quantity_label}</td>
                <td>{statusLabel(row.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

export function App() {
  const session = useUser();
  if (!session.ready) return <p className="page">Loading…</p>;
  if (!session.user) return <Login onSignedIn={session.setUser} />;
  const user = session.user;
  function signOut() {
    setToken(null);
    session.setUser(null);
  }
  return (
    <Shell user={user} onSignOut={signOut}>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/sites" element={<Sites />} />
        <Route path="/sites/:siteId" element={<SiteForm />} />
        <Route path="/batches" element={<Batches coordinator={user.role === "coordinator"} />} />
        <Route path="/batches/:batchId" element={user.role === "coordinator" ? <Planner /> : <Navigate to="/batches" replace />} />
        <Route path="/allocations" element={<Deliveries />} />
        <Route path="/allocations/:allocationId" element={<AllocationPage user={user} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}
