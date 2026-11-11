import { useEffect, useRef, useState } from "react";
import { postJson, useApi } from "./api.js";

const money = (value, digits = 0) =>
  value === null || value === undefined
    ? "—"
    : Number(value).toLocaleString("es", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Boton grande para abrir la publicacion original en una pestana nueva. */
export function OpenPostButton({ url, compact = false }) {
  if (!/^https?:\/\//i.test(url ?? "")) return null;
  return (
    <a className={compact ? "post-link" : "post-button"} href={url} target="_blank" rel="noreferrer"
      aria-label={compact ? "Ver publicación en Freelancer (pestaña nueva)" : undefined}>
      {compact ? "Ver" : "Ver publicación en Freelancer"}
      <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
        <path d="M9 2h5v5M14 2 7 9M12 9v4a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h4"
          fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </a>
  );
}

const POLL_MS = 5000;
// Postgres devuelve las claves del JSON ordenadas alfabeticamente; se muestran en orden logico.
const SCENARIO_ORDER = ["bajo", "medio", "alto"];

/** Lanza el pipeline (ingesta, clasificacion y rating) y sigue su estado mientras corre. */
export function IngestControl({ onFinished }) {
  const status = useApi("/api/pipeline/status");
  const [full, setFull] = useState(false);
  const [message, setMessage] = useState(null);
  const [starting, setStarting] = useState(false);
  const running = Boolean(status.data?.running);
  const wasRunning = useRef(false);
  const { reload } = status;

  useEffect(() => {
    if (wasRunning.current && !running) onFinished?.();
    wasRunning.current = running;
    if (!running) return undefined;
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [running, reload, onFinished]);

  async function start() {
    setStarting(true);
    setMessage(null);
    try {
      await postJson("/api/pipeline/run", { full });
      setMessage({ tone: "good", text: "Ingesta iniciada. Esta página se actualiza sola al terminar." });
      setTimeout(reload, 1500);
    } catch (error) {
      setMessage({ tone: "bad", text: error.message });
    } finally {
      setStarting(false);
    }
  }

  const last = status.data?.last_run;
  return (
    <section className="ingest-control" aria-label="Ejecutar ingesta">
      <div className="ingest-text">
        <h2>Ingesta manual</h2>
        <p className="muted">
          Trae los proyectos nuevos de Freelancer, los clasifica y puntúa los relevantes. Tarda unos minutos y la
          clasificación usa tu plan de Claude.
        </p>
        <label className="checkbox">
          <input type="checkbox" checked={full} onChange={(e) => setFull(e.target.checked)} disabled={running} />
          Corrida completa: más lenta, pero actualiza propuestas y estado de proyectos antiguos
        </label>
      </div>
      <div className="ingest-action">
        <button className="primary" onClick={start} disabled={running || starting}>
          {running ? "Ingesta en curso…" : starting ? "Iniciando…" : "Ejecutar ingesta ahora"}
        </button>
        <p className="muted" role="status" aria-live="polite">
          {running
            ? "Se comprueba cada 5 segundos."
            : last
              ? `Última: corrida #${last.id}, ${last.status}, ${last.items} proyectos.`
              : "Aún no hay corridas."}
        </p>
        {message ? <p className={`status ${message.tone}`}>{message.text}</p> : null}
      </div>
    </section>
  );
}

function List({ title, items }) {
  if (!items?.length) return null;
  return (
    <div>
      <h4>{title}</h4>
      <ul className="plain-list">{items.map((item) => <li key={item}>{item}</li>)}</ul>
    </div>
  );
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const area = useRef(null);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      area.current?.select();
    }
  }
  return (
    <>
      <textarea ref={area} className="draft" readOnly value={text} aria-label="Borrador de la propuesta" />
      <button onClick={copy}>{copied ? "Copiado" : "Copiar borrador"}</button>
    </>
  );
}

/** Presupuesto calculado en codigo y borrador redactado por IA para responder a un proyecto. */
export function ProposalPanel({ project }) {
  const proposal = useApi(`/api/projects/${project.id}/proposal`);
  const params = useApi("/api/budget/params");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const p = proposal.data;
  const labels = params.data?.tasks ?? {};

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      await postJson(`/api/projects/${project.id}/proposal`);
      proposal.reload();
    } catch (cause) {
      setError(cause.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card proposal" aria-label="Presupuesto y propuesta">
      <div className="proposal-head">
        <div>
          <h3>Presupuesto y propuesta</h3>
          <p className="muted">
            La IA identifica las tareas, el código calcula horas, precio y margen con tu tabla de horas, y la IA
            redacta un borrador con esas cifras. Nada se envía: lo revisas y lo publicas tú en Freelancer.
          </p>
        </div>
        <button className="primary" onClick={generate} disabled={busy} aria-describedby="proposal-cost">
          {busy ? "Generando… (hasta un minuto)" : p ? "Volver a generar" : "Generar presupuesto"}
        </button>
      </div>
      <p id="proposal-cost" className="muted">Cada generación hace dos llamadas a Claude Sonnet con tu plan.</p>
      {error ? <p className="notice bad" role="alert">{error}</p> : null}
      {busy ? <p className="muted" role="status" aria-live="polite">Analizando la publicación y calculando…</p> : null}

      {p ? (
        <div className="proposal-body">
          {p.warnings?.length ? (
            <ul className="notice warn-list">{p.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
          ) : null}

          <div className="price-row">
            <div>
              <p className="muted">Precio recomendado (escenario medio)</p>
              <p className="price">{money(p.recommended_price_local)} {p.currency}</p>
              {p.currency !== "USD" ? <p className="muted">≈ {money(p.recommended_price_usd)} USD</p> : null}
            </div>
            <div>
              <p className="muted">Plazo estimado</p>
              <p className="price">{p.delivery_days ?? "—"} días</p>
            </div>
            <p className="proposal-summary">{p.summary}</p>
          </div>

          <div className="table-wrap">
            <table>
              <caption className="muted">Escenarios calculados en código ({p.params_version})</caption>
              <thead>
                <tr><th scope="col">Escenario</th><th scope="col">Horas</th><th scope="col">Coste USD</th>
                  <th scope="col">Precio USD</th><th scope="col">Margen frente al máximo del cliente</th></tr>
              </thead>
              <tbody>
                {SCENARIO_ORDER.filter((name) => p.scenarios[name]).map((name) => [name, p.scenarios[name]]).map(([name, s]) => (
                  <tr key={name}>
                    <th scope="row">{name}</th>
                    <td className="num">{money(s.hours, 1)}</td>
                    <td className="num">{money(s.cost_usd)}</td>
                    <td className="num">{money(s.price_usd)}</td>
                    <td className={`num ${s.margin_usd < 0 ? "negative" : ""}`}>{money(s.margin_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="table-wrap">
            <table>
              <caption className="muted">Tareas que identificó la IA</caption>
              <thead><tr><th scope="col">Tarea</th><th scope="col">Unidades</th><th scope="col">Detalle</th><th scope="col">Lo dice la publicación</th></tr></thead>
              <tbody>
                {p.tasks.map((t, i) => (
                  <tr key={i}>
                    <td>{labels[t.type]?.label ?? (t.type === "otro" ? "Sin referencia" : t.type)}</td>
                    <td className="num">{t.units} {labels[t.type]?.unit ?? ""}</td>
                    <td className="value">{t.detail}</td>
                    <td className="value muted">{t.evidence ? `«${t.evidence}»` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="proposal-lists">
            <List title="Preguntas para el cliente" items={p.questions} />
            <List title="Información que falta" items={p.missing_info} />
            <List title="Señales de riesgo" items={p.red_flags} />
          </div>

          {p.draft ? (
            <div className="draft-block">
              <h4>Borrador de la propuesta ({p.draft_language})</h4>
              <CopyButton text={p.draft} />
            </div>
          ) : <p className="muted">Sin borrador: no se identificaron tareas que presupuestar.</p>}
          <p className="muted">Generado el {new Date(p.created_at).toLocaleString("es")} con {p.model ?? "—"}.</p>
        </div>
      ) : !busy ? <p className="muted">Todavía no hay presupuesto para este proyecto.</p> : null}
    </section>
  );
}
