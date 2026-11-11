import { useState } from "react";
import { postLabel, useApi } from "./api.js";
import GoldenSet from "./GoldenSet.jsx";
import { IngestControl, OpenPostButton, ProposalPanel } from "./Actions.jsx";
import { FIELDS } from "./fieldHelp.js";
import {
  CategoryChip, ClassificationExplain, ComplexityTag, FieldGuide, HelpButton, RatingExplain, RelevanceMeter,
} from "./Help.jsx";

const TABS = [
  ["inbox", "Bandeja de proyectos"],
  ["runs", "Salud de ingesta"],
  ["sources", "Fuentes"],
  ["quality", "Calidad del filtro"],
  ["costs", "Costos"],
  ["golden", "Golden set"],
];
const FIELD_NAMES = {
  title: "Título", description: "Descripción", budget_min: "Presupuesto mín.", budget_max: "Presupuesto máx.",
  currency: "Moneda", project_type: "Tipo", posted_at: "Publicado", bid_count: "Propuestas",
  status: "Estado", skills: "Skills", url: "URL",
};
const STATUS_TONE = {
  ok: "good", permitido: "good", parcial: "warn", en_curso: "warn", pendiente: "warn",
  bloqueada: "bad", cambio_estructura: "bad", prohibido: "bad",
};

const number = (value, digits = 0) =>
  value === null || value === undefined
    ? "—"
    : Number(value).toLocaleString("es", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const date = (value) =>
  value ? new Date(value).toLocaleString("es", { dateStyle: "short", timeStyle: "short" }) : "—";
const percent = (value) => (value === null || value === undefined ? "—" : `${number(value * 100, 1)} %`);
const display = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
};
const safeUrl = (value) => (/^https?:\/\//i.test(value ?? "") ? value : null);

function Status({ value }) {
  return <span className={`status ${STATUS_TONE[value] ?? ""}`}>{value?.replaceAll("_", " ") ?? "—"}</span>;
}

function Loader({ query, empty, children }) {
  if (query.error) return <p className="notice bad" role="alert">{query.error}. ¿Están en marcha la API y Postgres?</p>;
  if (!query.data) return <p className="muted">Cargando…</p>;
  if (empty?.(query.data)) return <p className="notice">{empty(query.data)}</p>;
  return children(query.data);
}

function Table({ head, withHelp = false, children }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h} scope="col">
                {withHelp && FIELDS[h] ? <span className="th-help">{h}<HelpButton field={h} /></span> : h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function AuditRow({ projectId, field, value, original, author, onSaved }) {
  const [wrong, setWrong] = useState(false);
  const [expected, setExpected] = useState("");
  const [message, setMessage] = useState(null);

  async function save(isCorrect) {
    setMessage(null);
    try {
      await postLabel(projectId, {
        field, is_correct: isCorrect, author, expected_value: isCorrect ? null : expected,
      });
      setMessage({ tone: "good", text: "Guardado" });
      setWrong(false);
      onSaved();
    } catch (error) {
      setMessage({ tone: "bad", text: error.message });
    }
  }

  return (
    <tr>
      <th scope="row">{FIELD_NAMES[field]}</th>
      <td className="value">{display(value)}</td>
      <td className="value muted">{display(original)}</td>
      <td><div className="actions">
        <button disabled={!author} onClick={() => save(true)}>Correcto</button>
        <button disabled={!author} onClick={() => setWrong(!wrong)} aria-expanded={wrong}>Incorrecto</button>
        {wrong && (
          <form onSubmit={(e) => { e.preventDefault(); save(false); }}>
            <input
              aria-label={`Valor correcto de ${FIELD_NAMES[field]}`} placeholder="Valor correcto"
              value={expected} onChange={(e) => setExpected(e.target.value)} required
            />
            <button type="submit">Guardar</button>
          </form>
        )}
        {message && <span className={`status ${message.tone}`} role="status">{message.text}</span>}
      </div></td>
    </tr>
  );
}

const ORIGINAL_VALUE = {
  title: (o) => o.title,
  description: (o) => o.description ?? o.preview_description,
  budget_min: (o) => o.budget?.minimum,
  budget_max: (o) => o.budget?.maximum,
  currency: (o) => o.currency?.code,
  project_type: (o) => o.type,
  posted_at: (o) => (o.submitdate ? new Date(o.submitdate * 1000).toISOString() : null),
  bid_count: (o) => o.bid_stats?.bid_count,
  status: (o) => o.status,
  skills: (o) => o.jobs?.map((j) => j.name),
  url: (o) => o.seo_url,
};

function ProjectDetail({ id, onClose }) {
  const detail = useApi(`/api/projects/${id}`);
  const audit = useApi(`/api/projects/${id}/audit`);
  const [author, setAuthor] = useState(() => {
    try { return localStorage.getItem("author") ?? ""; } catch { return ""; }
  });
  const changeAuthor = (value) => {
    setAuthor(value);
    try { localStorage.setItem("author", value); } catch { /* preferencia opcional */ }
  };

  return (
    <section className="detail" aria-label="Detalle del proyecto">
      <button className="close" onClick={onClose}>Volver a la bandeja</button>
      <Loader query={detail}>
        {(p) => (
          <>
            <div className="detail-head">
              <div>
                <h2>{p.title}</h2>
                <p className="muted">
                  {p.source} · corrida #{p.source_run_id ?? "—"} · perfil v{p.profile_version ?? "—"}
                </p>
              </div>
              <OpenPostButton url={safeUrl(p.url)} />
            </div>
            <div className="cards">
              <div className="card">
                <h3>Por qué esta categoría</h3>
                <ClassificationExplain project={p} />
              </div>
              <div className="card">
                <h3>Por qué esta nota</h3>
                <RatingExplain project={p} />
              </div>
            </div>

            <ProposalPanel project={p} />

            <h3>Auditoría de extracción</h3>
            <label className="author">
              Tu nombre, para firmar las etiquetas
              <input value={author} onChange={(e) => changeAuthor(e.target.value)} maxLength={80} />
            </label>
            <Loader query={audit}>
              {(a) => (
                <>
                  {!a.original && <p className="notice bad">No se encontró el snapshot original de este proyecto.</p>}
                  <Table head={["Campo", "Extraído", "Snapshot original", "Revisión"]}>
                    {Object.entries(a.fields).map(([field, value]) => (
                      <AuditRow
                        key={field} projectId={id} field={field} value={value} author={author.trim()}
                        original={a.original ? ORIGINAL_VALUE[field](a.original) : null} onSaved={detail.reload}
                      />
                    ))}
                  </Table>
                </>
              )}
            </Loader>

            <h3>Etiquetas ({p.labels.length})</h3>
            {p.labels.length === 0 ? <p className="muted">Todavía no hay etiquetas.</p> : (
              <Table head={["Campo", "Valor esperado", "Autor", "Fecha"]}>
                {p.labels.map((l, i) => (
                  <tr key={i}><td>{l.field}</td><td className="value">{display(l.expected_value)}</td><td>{l.author}</td><td>{date(l.created_at)}</td></tr>
                ))}
              </Table>
            )}

            <h3>Historial de versiones ({p.versions.length})</h3>
            <Table head={["Fecha", "Corrida", "Cambios"]}>
              {p.versions.map((v) => (
                <tr key={v.id}>
                  <td>{date(v.captured_at)}</td><td>#{v.run_id}</td>
                  <td className="value">
                    {Object.entries(v.changed_fields).map(([f, c]) => `${f}: ${display(c.old)} → ${display(c.new)}`).join(" · ")}
                  </td>
                </tr>
              ))}
            </Table>
          </>
        )}
      </Loader>
    </section>
  );
}

const PAGE_SIZE = 50;

function FacetSelect({ label, value, onChange, options, render = (o) => o.value }) {
  return (
    <label>{label}
      <select value={value} onChange={onChange}>
        <option value="">Todos</option>
        {options.map((o) => <option key={o.value} value={o.value}>{render(o)} ({o.n})</option>)}
      </select>
    </label>
  );
}

function Market({ project }) {
  if (!project.market_country) return "—";
  return (
    <span title={project.market_approximate ? "Aproximado: país de la moneda, la publicación no lo menciona" : "Mencionado en la publicación"}>
      {project.market_approximate ? "≈ " : ""}{project.market_country}
      <span className="muted"> · {project.market_region}</span>
    </span>
  );
}

function Inbox() {
  const [filters, setFilters] = useState({
    category: "", complexity: "", region: "", country: "", currency: "", language: "",
    min_relevance: "", min_rating: "", min_budget_usd: "", posted_since: "",
  });
  const facets = useApi("/api/facets");
  const facetData = facets.data ?? { regions: [], countries: [], currencies: [], languages: [] };
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState(null);
  const params = new URLSearchParams({ limit: PAGE_SIZE, offset });
  Object.entries(filters).forEach(([key, value]) => value !== "" && params.set(key, value));
  const query = useApi(`/api/projects?${params}`);
  const set = (key) => (event) => {
    setOffset(0);
    setFilters({ ...filters, [key]: event.target.value });
  };

  if (selected) return <ProjectDetail id={selected} onClose={() => setSelected(null)} />;

  return (
    <>
      <form className="filters" onSubmit={(e) => e.preventDefault()}>
        <label>Categoría
          <select value={filters.category} onChange={set("category")}>
            <option value="">Todas</option>
            <option value="sin_clasificar">Sin clasificar</option>
            <option value="marketing">Marketing</option>
            <option value="seo">SEO</option>
            <option value="ia_automatizacion">IA y automatización</option>
            <option value="web_simple">Web simple</option>
            <option value="ux_ui">UX/UI</option>
            <option value="otra">Otra</option>
          </select>
        </label>
        <label>Complejidad
          <select value={filters.complexity} onChange={set("complexity")}>
            <option value="">Todas</option>
            <option value="baja">Baja</option>
            <option value="media">Media</option>
            <option value="alta">Alta</option>
          </select>
        </label>
        <FacetSelect label="Región" value={filters.region} onChange={set("region")} options={facetData.regions} />
        <FacetSelect label="País" value={filters.country} onChange={set("country")} options={facetData.countries}
          render={(o) => `${o.value}${o.mentioned ? "" : " ≈"}`} />
        <FacetSelect label="Moneda" value={filters.currency} onChange={set("currency")} options={facetData.currencies} />
        <FacetSelect label="Idioma" value={filters.language} onChange={set("language")} options={facetData.languages} />
        <label>Relevancia mín.
          <input type="number" min="0" max="1" step="0.1" value={filters.min_relevance} onChange={set("min_relevance")} />
        </label>
        <label>Rating mín.
          <input type="number" min="0" max="100" value={filters.min_rating} onChange={set("min_rating")} />
        </label>
        <label>Presupuesto mín. (USD)
          <input type="number" min="0" value={filters.min_budget_usd} onChange={set("min_budget_usd")} />
        </label>
        <label>Publicado desde
          <input type="date" value={filters.posted_since} onChange={set("posted_since")} />
        </label>
      </form>
      <Loader query={query} empty={(d) => d.total === 0 && "No hay proyectos con estos filtros. Si no has lanzado ninguna ingesta, ejecuta: python -m scripts.ingest freelancer"}>
        {(d) => (
          <>
            <p className="muted">
              {number(d.total)} proyectos · País con ≈: aproximado por la moneda, porque la publicación no lo menciona.
            </p>
            <FieldGuide />
            <Table withHelp head={["Proyecto", "Categoría", "Relev.", "Compl.", "Rating", "Mercado", "Presupuesto", "Máx. USD", "Propuestas", "Publicado", "Corrida", "Publicación"]}>
              {d.items.map((p) => (
                <tr key={p.id}>
                  <td><button className="link" onClick={() => setSelected(p.id)}>{p.title}</button></td>
                  <td>{p.category ? <CategoryChip category={p.category} /> : <span className="muted">{p.needs_review ? "a revisar" : "sin clasificar"}</span>}</td>
                  <td><RelevanceMeter value={p.relevance} /></td>
                  <td><ComplexityTag value={p.complexity} /></td>
                  <td className="num">{number(p.rating)}</td>
                  <td><Market project={p} /></td>
                  <td className="num">{number(p.budget_min)}–{number(p.budget_max)} {p.currency}</td>
                  <td className="num">{number(p.budget_usd)}</td>
                  <td className="num">{number(p.bid_count)}</td>
                  <td>{date(p.posted_at)}</td>
                  <td className="num">#{p.source_run_id ?? "—"}</td>
                  <td><OpenPostButton url={safeUrl(p.url)} compact /></td>
                </tr>
              ))}
            </Table>
            <div className="pager">
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Anterior</button>
              <button disabled={offset + PAGE_SIZE >= d.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Siguiente</button>
            </div>
          </>
        )}
      </Loader>
    </>
  );
}

function Runs() {
  const query = useApi("/api/runs");
  return (
    <>
    <IngestControl onFinished={query.reload} />
    <Loader query={query} empty={(d) => d.length === 0 && "Aún no hay corridas. Usa el botón de arriba para lanzar la primera."}>
      {(rows) => (
        <Table head={["Corrida", "Fuente", "Perfil", "Modo", "Estado", "Inicio", "Duración (s)", "Páginas", "Ítems", "Cobertura", "Costo USD", "Errores", "Detalle"]}>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="num">#{r.id}</td><td>{r.source}</td><td>v{r.profile_version}</td>
              <td title={r.since ? `Desde ${date(r.since)}` : "Pide todo lo publicado"}>{r.mode}</td>
              <td><Status value={r.status} /></td><td>{date(r.started_at)}</td>
              <td className="num">{number(r.duration_seconds)}</td><td className="num">{number(r.pages)}</td>
              <td className="num">{number(r.items)}</td>
              <td className="num" title="Proyectos descargados frente a los que la fuente dice tener en cada búsqueda">{percent(r.coverage)}</td>
              <td className="num">{number(r.cost_usd, 2)}</td>
              <td className="num">{number(r.error_count)}</td>
              <td className="value">{r.errors.slice(0, 3).join(" · ")}</td>
            </tr>
          ))}
        </Table>
      )}
    </Loader>
    </>
  );
}

function Sources() {
  const query = useApi("/api/sources");
  return (
    <Loader query={query} empty={(d) => d.length === 0 && "El registro se carga con la primera ingesta."}>
      {(rows) => (
        <Table head={["Fuente", "Estado legal", "Acceso", "Activa", "Proyectos", "Rating", "Desglose", "Notas"]}>
          {rows.map((s) => (
            <tr key={s.id}>
              <td>{safeUrl(s.terms_url) ? <a href={safeUrl(s.terms_url)} target="_blank" rel="noreferrer">{s.name}</a> : s.name}</td>
              <td><Status value={s.legal_status} /></td><td>{s.access_mode}</td><td>{s.active ? "Sí" : "No"}</td>
              <td className="num">{number(s.project_count)}</td>
              <td className="num">{number(s.rating)}{s.rating !== null && <div className="muted">#{s.rating_run_id} · {s.rubric_version}</div>}</td>
              <td className="value">{display(s.breakdown)}</td><td className="value">{s.legal_notes}</td>
            </tr>
          ))}
        </Table>
      )}
    </Loader>
  );
}

function Quality() {
  const query = useApi("/api/filter-quality");
  return (
    <Loader query={query} empty={(d) => d.length === 0 && "Sin datos: hacen falta el agente clasificador y etiquetas de categoría del golden set."}>
      {(reports) => reports.map((r) => (
        <section key={r.prompt_version}>
          <h3>Prompt {r.prompt_version ?? "sin versión"} · {r.n} proyectos</h3>
          <Table head={["Categoría", "Precisión", "Recall", "Casos"]}>
            {r.categories.map((c) => (
              <tr key={c}><th scope="row">{c}</th><td className="num">{percent(r.per_category[c].precision)}</td><td className="num">{percent(r.per_category[c].recall)}</td><td className="num">{r.per_category[c].support}</td></tr>
            ))}
          </Table>
          <h4>Matriz de confusión (filas: esperado; columnas: predicho)</h4>
          <Table head={["", ...r.categories]}>
            {r.categories.map((e) => (
              <tr key={e}><th scope="row">{e}</th>{r.categories.map((p) => <td className="num" key={p}>{r.matrix[e][p]}</td>)}</tr>
            ))}
          </Table>
        </section>
      ))}
    </Loader>
  );
}

function Costs() {
  const query = useApi("/api/costs");
  return (
    <Loader query={query}>
      {(d) => (
        <>
          <h3>Por agente</h3>
          {d.by_agent.length === 0 ? <p className="notice">Sin llamadas a agentes todavía.</p> : (
            <Table head={["Agente", "Modelo", "Prompt", "Llamadas", "Tokens entrada", "Tokens salida", "USD"]}>
              {d.by_agent.map((a, i) => (
                <tr key={i}><td>{a.agent}</td><td>{a.model}</td><td>{a.prompt_version}</td><td className="num">{number(a.calls)}</td><td className="num">{number(a.input_tokens)}</td><td className="num">{number(a.output_tokens)}</td><td className="num">{number(a.cost_usd, 4)}</td></tr>
              ))}
            </Table>
          )}
          <h3>Por corrida</h3>
          <Table head={["Corrida", "Fuente", "Llamadas", "Tokens entrada", "Tokens salida", "USD", "USD por proyecto"]}>
            {d.by_run.map((r) => (
              <tr key={r.run_id}><td className="num">#{r.run_id}</td><td>{r.source}</td><td className="num">{number(r.calls)}</td><td className="num">{number(r.input_tokens)}</td><td className="num">{number(r.output_tokens)}</td><td className="num">{number(r.cost_usd, 4)}</td><td className="num">{number(r.cost_per_project, 4)}</td></tr>
            ))}
          </Table>
        </>
      )}
    </Loader>
  );
}

const VIEWS = { inbox: Inbox, runs: Runs, sources: Sources, quality: Quality, costs: Costs, golden: GoldenSet };

export default function App() {
  const [tab, setTab] = useState("inbox");
  const View = VIEWS[tab];
  return (
    <>
      <header>
        <h1>Dashboard de validación</h1>
        <nav aria-label="Vistas">
          {TABS.map(([id, label]) => (
            <button key={id} className={id === tab ? "active" : ""} aria-current={id === tab ? "page" : undefined} onClick={() => setTab(id)}>{label}</button>
          ))}
        </nav>
      </header>
      <main><View /></main>
    </>
  );
}
