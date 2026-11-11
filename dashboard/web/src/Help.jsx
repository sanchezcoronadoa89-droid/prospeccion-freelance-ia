import { useId, useRef, useState } from "react";
import { useApi } from "./api.js";
import {
  CATEGORIES, CATEGORY_LABEL, COMPLEXITY, FIELDS, FIELD_TITLES, ORIGINS, QUESTIONS, RATING_CRITERIA,
  RATING_PENALTIES, RELEVANCE_BANDS, RELEVANCE_THRESHOLD, relevanceBand,
} from "./fieldHelp.js";

const fmt = (value, digits = 2) =>
  Number(value).toLocaleString("es", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export function OriginTag({ origin }) {
  return (
    <span className={`origin origin-${origin}`} title={ORIGINS[origin].text}>
      <span className="origin-mark" aria-hidden="true" />
      {ORIGINS[origin].label}
    </span>
  );
}

export function CategoryChip({ category }) {
  return <span className={`cat cat-${category}`}>{CATEGORY_LABEL[category] ?? category}</span>;
}

export function RelevanceMeter({ value }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  const band = relevanceBand(Number(value));
  return (
    <span className="meter" title={`${band.label}: ${band.text}`}>
      <span className="meter-track" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={Number(value)}
        aria-label={`Relevancia ${fmt(value)}, ${band.label}`}>
        <span className={`meter-fill ${Number(value) >= RELEVANCE_THRESHOLD ? "is-relevant" : ""}`}
          style={{ width: `${Number(value) * 100}%` }} />
        <span className="meter-threshold" style={{ left: `${RELEVANCE_THRESHOLD * 100}%` }} aria-hidden="true" />
      </span>
      <span className="meter-value">{fmt(value)}</span>
    </span>
  );
}

export function ComplexityTag({ value }) {
  const info = COMPLEXITY.find((c) => c.key === value);
  if (!info) return <span className="muted">—</span>;
  return (
    <span className="complexity" title={info.text}>
      <span className="complexity-steps" aria-hidden="true">
        {COMPLEXITY.map((c) => <span key={c.key} className={c.level <= info.level ? "on" : ""} />)}
      </span>
      {info.label}
    </span>
  );
}

/** Boton «?» que abre una ficha en la capa superior: funciona con clic, teclado (Esc) y tactil. */
export function HelpButton({ field }) {
  const info = FIELDS[field];
  const id = useId();
  const popover = useRef(null);
  if (!info) return null;
  const title = FIELD_TITLES[field] ?? field;

  function place(event) {
    const rect = event.currentTarget.getBoundingClientRect();
    const width = Math.min(320, window.innerWidth - 32);
    const left = Math.min(Math.max(16, rect.left - 12), window.innerWidth - width - 16);
    Object.assign(popover.current.style, { top: `${rect.bottom + 8}px`, left: `${left}px`, width: `${width}px` });
  }

  return (
    <>
      <button type="button" className="help-button" popoverTarget={id} onClick={place}
        aria-label={`Qué significa ${title}`}>?</button>
      <div id={id} ref={popover} popover="auto" className="help-popover" role="dialog" aria-label={title}>
        <p className="help-title">{title}</p>
        <OriginTag origin={info.origin} />
        <p>{info.short}</p>
        {info.more ? <p className="muted">{info.more}</p> : null}
        {field === "Relev." ? <RelevanceScale compact /> : null}
        {field === "Compl." ? <ComplexityScale /> : null}
      </div>
    </>
  );
}

function RelevanceScale({ compact = false }) {
  return (
    <ul className={`scale ${compact ? "compact" : ""}`}>
      {RELEVANCE_BANDS.map((band, index) => {
        const upper = index === 0 ? 1 : RELEVANCE_BANDS[index - 1].min - 0.1;
        return (
          <li key={band.label}>
            <span className="scale-range">{fmt(band.min, 1)}–{fmt(upper, 1)}</span>
            <span><strong>{band.label}.</strong> {band.text}</span>
          </li>
        );
      })}
    </ul>
  );
}

function ComplexityScale() {
  return (
    <ul className="scale">
      {COMPLEXITY.map((c) => (
        <li key={c.key}><ComplexityTag value={c.key} /><span>{c.text}</span></li>
      ))}
    </ul>
  );
}

function RatingFormula() {
  const rubric = useApi("/api/rubric");
  if (!rubric.data) return null;
  const { weights, penalties, version } = rubric.data;
  return (
    <div className="formula">
      <p>La IA puntúa cada criterio de 0 a 5. El código convierte cada puntuación en puntos según su peso y resta las penalizaciones.</p>
      <ul className="weights">
        {Object.entries(weights).map(([key, weight]) => (
          <li key={key}>
            <span>{RATING_CRITERIA[key] ?? key}</span>
            <span className="weight-bar" aria-hidden="true"><span style={{ width: `${weight}%` }} /></span>
            <span className="num">{weight} pts</span>
          </li>
        ))}
        {Object.entries(penalties).map(([key, points]) => (
          <li key={key} className="penalty">
            <span>{RATING_PENALTIES[key] ?? key}</span>
            <span aria-hidden="true" />
            <span className="num">−{points} pts</span>
          </li>
        ))}
      </ul>
      <p className="muted">Rúbrica {version}.</p>
    </div>
  );
}

const GUIDE_KEY = "guia-bandeja-abierta";

function readGuideOpen() {
  try {
    return localStorage.getItem(GUIDE_KEY) !== "no";
  } catch {
    return true;
  }
}

/** Guia de lectura de la bandeja: abierta la primera vez, despues recuerda tu eleccion. */
export function FieldGuide() {
  const [open, setOpen] = useState(readGuideOpen);

  function toggle(event) {
    const next = event.currentTarget.open;
    setOpen(next);
    try {
      localStorage.setItem(GUIDE_KEY, next ? "si" : "no");
    } catch {
      /* preferencia opcional */
    }
  }

  return (
    <details className="guide" open={open} onToggle={toggle}>
      <summary>Cómo leer la bandeja</summary>
      <div className="guide-body">
        <section className="guide-origins" aria-label="Procedencia de los datos">
          <p>Cada dato tiene una procedencia, y de ella depende cuánto puedes fiarte:</p>
          <ul>
            {Object.entries(ORIGINS).map(([key, origin]) => (
              <li key={key}><OriginTag origin={key} /><span>{origin.text}</span></li>
            ))}
          </ul>
        </section>

        <section aria-label="Columnas por pregunta">
          <dl className="guide-questions">
            {QUESTIONS.map((group) => (
              <div key={group.question} className="guide-question">
                <dt>{group.question}</dt>
                {group.fields.map((field) => (
                  <dd key={field}>
                    <span className="guide-field">{FIELD_TITLES[field] ?? field}</span>
                    <OriginTag origin={FIELDS[field].origin} />
                    <span className="guide-text">{FIELDS[field].short}</span>
                  </dd>
                ))}
              </div>
            ))}
          </dl>
        </section>

        <details className="guide-more">
          <summary>Categorías: qué incluye cada una</summary>
          <p className="muted">El agente elige el entregable principal. Una mención de pasada no cambia la categoría.</p>
          <ul className="category-grid">
            {CATEGORIES.map((c) => (
              <li key={c.key}>
                <CategoryChip category={c.key} />
                <p>{c.includes}</p>
                <p className="muted">Ejemplo: {c.example}</p>
              </li>
            ))}
          </ul>
        </details>

        <details className="guide-more">
          <summary>Relevancia y complejidad: escalas</summary>
          <div className="guide-scales">
            <div>
              <p className="guide-field">Relevancia</p>
              <RelevanceScale />
              <p className="muted">La marca en la barra señala 0,5, el umbral para considerarlo relevante.</p>
            </div>
            <div>
              <p className="guide-field">Complejidad</p>
              <ComplexityScale />
            </div>
          </div>
        </details>

        <details className="guide-more">
          <summary>Rating: cómo se calcula la nota</summary>
          <RatingFormula />
        </details>
      </div>
    </details>
  );
}

/** Por que este proyecto tiene esta categoria y este encaje. */
export function ClassificationExplain({ project }) {
  if (!project.category) {
    return (
      <p className="muted">
        {project.needs_review ? `A revisar: ${project.justification}` : "Sin clasificar: pendiente, o reservado para el golden set."}
      </p>
    );
  }
  return (
    <div className="explain">
      <div className="explain-row">
        <CategoryChip category={project.category} />
        <RelevanceMeter value={project.relevance} />
        <ComplexityTag value={project.complexity} />
      </div>
      <p className="explain-why">{project.justification}</p>
      <p className="muted">
        <OriginTag origin={project.class_model ? "agent" : "code"} /> {project.class_model ?? "Regla sin IA"}, corrida #{project.class_run_id}, {project.prompt_version}
      </p>
    </div>
  );
}

/** Desglose de la nota: criterio, puntuacion, peso y puntos, igual que lo calcula el codigo. */
export function RatingExplain({ project }) {
  const rubric = useApi("/api/rubric");
  const breakdown = project.rating_breakdown;
  if (project.rating === null || project.rating === undefined) {
    return <p className="muted">Sin nota: solo se puntúan los proyectos con relevancia desde 0,5.</p>;
  }
  if (!rubric.data || !breakdown) return <p><strong>{fmt(project.rating, 0)}</strong> / 100</p>;
  const { weights, penalties } = rubric.data;
  const total = Object.values(weights).reduce((sum, w) => sum + w, 0);
  return (
    <div className="explain">
      <p className="rating-total"><strong>{fmt(project.rating, 0)}</strong> / 100</p>
      <table className="rating-table">
        <caption className="muted">Cómo se llega a la nota</caption>
        <thead>
          <tr><th scope="col">Criterio</th><th scope="col">IA (0–5)</th><th scope="col" className="num">Puntos</th></tr>
        </thead>
        <tbody>
          {Object.entries(weights).map(([key, weight]) => (
            <tr key={key}>
              <th scope="row">{RATING_CRITERIA[key] ?? key}</th>
              <td>
                <span className="dots" aria-label={`${breakdown[key]} de 5`}>
                  {[1, 2, 3, 4, 5].map((n) => <span key={n} className={n <= breakdown[key] ? "on" : ""} />)}
                </span>
              </td>
              <td className="num">{fmt((weight * breakdown[key]) / 5 / total * 100, 1)} de {fmt(weight / total * 100, 0)}</td>
            </tr>
          ))}
          {Object.entries(penalties).filter(([key]) => breakdown[key]).map(([key, points]) => (
            <tr key={key} className="penalty">
              <th scope="row">{RATING_PENALTIES[key] ?? key}</th><td>Sí</td><td className="num">−{points}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {breakdown.notes ? <p className="explain-why">{breakdown.notes}</p> : null}
      <p className="muted"><OriginTag origin="agent" /> puntúa los criterios · <OriginTag origin="code" /> calcula la nota · {project.rubric_version}</p>
    </div>
  );
}
