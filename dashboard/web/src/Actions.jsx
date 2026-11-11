import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
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

const POLL_RUNNING_MS = 5000;
// En reposo tambien se consulta: detecta corridas lanzadas desde la consola y mantiene vivo el "hace X".
const POLL_IDLE_MS = 60000;
const STALE_HOURS = 24;
// Postgres devuelve las claves del JSON ordenadas alfabeticamente; se muestran en orden logico.
const SCENARIO_ORDER = ["bajo", "medio", "alto"];

const PipelineContext = createContext(null);
const usePipeline = () => useContext(PipelineContext);

const hoursSince = (value) => (Date.now() - new Date(value).getTime()) / 3_600_000;

function relativeTime(value) {
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  const format = new Intl.RelativeTimeFormat("es", { numeric: "auto" });
  if (minutes < 1) return "hace un momento";
  if (minutes < 60) return format.format(-minutes, "minute");
  if (minutes < 48 * 60) return format.format(-Math.round(minutes / 60), "hour");
  return format.format(-Math.round(minutes / 1440), "day");
}

// El proceso tarda unos segundos en arrancar y tomar el bloqueo: hasta verlo, el boton sigue ocupado.
const START_GRACE_MS = 45000;

function finishedMessage(run, baselineId) {
  if (!run || (baselineId !== undefined && run.id === baselineId)) {
    return { tone: "bad", text: "La actualización terminó sin registrar una corrida nueva. Revisa el log en data/logs." };
  }
  const items = `${run.items ?? 0} proyectos revisados`;
  return run.status === "ok"
    ? { tone: "good", text: `Listo: ${items}. La bandeja ya muestra lo nuevo.` }
    : { tone: "warn", text: `Terminó con estado «${run.status.replaceAll("_", " ")}» (${items}). Mira Salud de ingesta.` };
}

/** Estado del pipeline compartido por el boton Actualizar y el panel de Salud de ingesta. */
export function PipelineProvider({ onFinished, children }) {
  const status = useApi("/api/pipeline/status");
  const [starting, setStarting] = useState(false);
  const [message, setMessage] = useState(null);
  // Lanzada desde aqui y aun sin confirmar: { since, baselineId } con la ultima corrida previa.
  const [pending, setPending] = useState(null);
  const running = Boolean(status.data?.running);
  const wasRunning = useRef(false);
  const baseline = useRef(undefined);
  const { reload } = status;
  const data = status.data;

  useEffect(() => {
    if (!data) return;
    const lastId = data.last_run?.id;
    const finish = () => {
      setMessage(finishedMessage(data.last_run, baseline.current));
      baseline.current = undefined;
      setPending(null);
      onFinished?.();
    };
    if (data.running) {
      setPending(null);
    } else if (wasRunning.current) {
      finish();
    } else if (pending && lastId !== pending.baselineId) {
      finish(); // Termino entre dos consultas: no llegamos a verla en curso.
    } else if (pending && Date.now() - pending.since > START_GRACE_MS) {
      setPending(null);
      baseline.current = undefined;
      setMessage({ tone: "bad", text: "La actualización no llegó a arrancar. Revisa el log en data/logs." });
    }
    wasRunning.current = data.running;
  }, [data, pending, onFinished]);

  const fastPoll = running || Boolean(pending);
  useEffect(() => {
    const timer = setInterval(reload, fastPoll ? POLL_RUNNING_MS : POLL_IDLE_MS);
    return () => clearInterval(timer);
  }, [fastPoll, reload]);

  // Los avisos de exito se retiran solos; los errores se quedan hasta el siguiente intento.
  useEffect(() => {
    if (message?.tone !== "good" || fastPoll) return undefined;
    const timer = setTimeout(() => setMessage(null), 10000);
    return () => clearTimeout(timer);
  }, [message, fastPoll]);

  const start = useCallback(async (full = false) => {
    setStarting(true);
    setMessage(null);
    const baselineId = data?.last_run?.id;
    try {
      await postJson("/api/pipeline/run", { full });
      baseline.current = baselineId;
      setPending({ since: Date.now(), baselineId });
      setMessage({ tone: "good", text: "Buscando proyectos nuevos. Puedes seguir trabajando: la página se actualiza sola." });
      setTimeout(reload, 1500);
    } catch (error) {
      setMessage({ tone: "bad", text: error.message });
    } finally {
      setStarting(false);
    }
  }, [reload, data]);

  const value = {
    data, error: status.error, running: running || Boolean(pending), starting, message, start,
  };
  return (
    <PipelineContext.Provider value={value}>
      {children}
    </PipelineContext.Provider>
  );
}

function RefreshIcon({ spinning }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16" className={spinning ? "spin" : undefined}>
      <path d="M13.5 8A5.5 5.5 0 1 1 11.9 4.1M13.5 2v3h-3" fill="none" stroke="currentColor" strokeWidth="1.8"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Explica, sin inventar, cada cuanto se buscan proyectos solos. */
function ScheduleInfo({ every, last }) {
  const id = useId();
  const popover = useRef(null);

  function place(event) {
    const rect = event.currentTarget.getBoundingClientRect();
    const width = Math.min(340, window.innerWidth - 32);
    const left = Math.min(Math.max(16, rect.right - width), window.innerWidth - width - 16);
    Object.assign(popover.current.style, { top: `${rect.bottom + 8}px`, left: `${left}px`, width: `${width}px` });
  }

  const next = every && last ? new Date(new Date(last.started_at).getTime() + every * 3_600_000) : null;
  return (
    <>
      <button type="button" className="update-info" popoverTarget={id} onClick={place}>
        {every ? `Automática cada ${every} h` : "¿Cada cuánto se actualiza?"}
      </button>
      <div id={id} ref={popover} popover="auto" className="help-popover" role="dialog" aria-label="Cada cuánto se actualiza">
        <p className="help-title">Cada cuánto se actualiza</p>
        {every ? (
          <>
            <p><strong>Automáticamente cada {every} horas.</strong>
              {next ? ` La próxima, hacia las ${next.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}.` : ""}</p>
            <p>Si no quieres esperar, pulsa <strong>Actualizar</strong> y se busca al momento.</p>
          </>
        ) : (
          <>
            <p><strong>Solo cuando pulsas Actualizar.</strong> La búsqueda automática aún no está programada.</p>
            <p className="muted">
              Programarla necesita tu autorización y confirmar que tu permiso de Freelancer cubre el acceso
              automatizado. Mientras tanto, conviene actualizar al menos una vez al día.
            </p>
          </>
        )}
        <p className="muted">
          Cada actualización trae lo publicado desde la anterior, lo clasifica y lo puntúa. Tarda unos minutos y la
          clasificación usa tu plan de Claude. La corrida completa está en Salud de ingesta.
        </p>
      </div>
    </>
  );
}

/** Llamada a la accion principal de la cabecera: buscar proyectos nuevos ahora. */
export function UpdateButton() {
  const { data, error, running, starting, message, start } = usePipeline();
  const last = data?.last_run;
  const when = last ? last.finished_at ?? last.started_at : null;
  const failed = last && !["ok", "parcial", "en_curso"].includes(last.status);
  const stale = !running && when && (failed || hoursSince(when) > STALE_HOURS);
  const busy = running || starting;

  let meta;
  if (error) meta = "Sin conexión con la API";
  else if (running) meta = "Buscando proyectos nuevos…";
  else if (failed) meta = `Última actualización ${last.status.replaceAll("_", " ")} ${relativeTime(when)}`;
  else if (when) meta = `Actualizado ${relativeTime(when)}`;
  else meta = "Aún sin actualizar";

  return (
    <div className="update">
      <div className="update-meta">
        <span className={`update-when ${stale ? "stale" : ""}`} role="status" aria-live="polite">
          {stale ? <span className="dot" aria-hidden="true" /> : null}{meta}
        </span>
        <ScheduleInfo every={data?.auto_update_every_hours} last={last} />
      </div>
      <button type="button" className="cta" onClick={() => start(false)} disabled={busy || Boolean(error)}
        aria-busy={busy} title="Busca ahora en Freelancer los proyectos publicados desde la última actualización">
        <RefreshIcon spinning={busy} />
        {running ? "Actualizando…" : starting ? "Iniciando…" : "Actualizar"}
      </button>
      {message ? <p className={`update-message ${message.tone}`} role={message.tone === "bad" ? "alert" : "status"}>{message.text}</p> : null}
    </div>
  );
}

/** Opciones avanzadas de la ingesta, dentro de Salud de ingesta. */
export function IngestControl() {
  const { data: status, running, starting, start } = usePipeline();
  const [full, setFull] = useState(false);

  const last = status?.last_run;
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
        <button className="primary" onClick={() => start(full)} disabled={running || starting}>
          {running ? "Ingesta en curso…" : starting ? "Iniciando…" : "Ejecutar ingesta ahora"}
        </button>
        <p className="muted">
          {running
            ? "Se comprueba cada 5 segundos. El progreso también se ve en el botón Actualizar."
            : last
              ? `Última: corrida #${last.id}, ${last.status}, ${last.items} proyectos.`
              : "Aún no hay corridas."}
        </p>
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
