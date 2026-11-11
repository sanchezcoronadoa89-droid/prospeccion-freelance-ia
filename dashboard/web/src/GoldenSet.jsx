import { useState } from "react";
import { postGoldenLabel, useApi } from "./api.js";

const CATEGORIES = [
  ["marketing", "Marketing"], ["seo", "SEO"], ["ia_automatizacion", "IA y automatización"],
  ["web_simple", "Web simple"], ["ux_ui", "UX/UI"], ["otra", "Otra"],
];
const RELEVANCE = [[true, "Sí"], [false, "No"]];
const COMPLEXITY = [["baja", "Baja"], ["media", "Media"], ["alta", "Alta"]];
const QUALITY = [[1, "1"], [2, "2"], [3, "3"], [4, "4"], [5, "5"]];
const FIELD_NAMES = { category: "Categoría", relevant: "Relevante", complexity: "Complejidad", quality: "Calidad" };

function readAuthor() {
  try {
    return localStorage.getItem("author") ?? "";
  } catch {
    return "";
  }
}

function saveAuthor(value) {
  try {
    localStorage.setItem("author", value);
  } catch {
    /* preferencia opcional */
  }
}

const formatKappa = (value) => value.toLocaleString("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const formatAnswer = (value) => (value === true ? "Sí" : value === false ? "No" : String(value));

function Choice({ legend, name, options, value, onChange }) {
  return (
    <fieldset className="choice">
      <legend>{legend}</legend>
      {options.map(([option, label]) => (
        <label key={String(option)} className={value === option ? "selected" : ""}>
          <input type="radio" name={name} checked={value === option} onChange={() => onChange(option)} required />
          {label}
        </label>
      ))}
    </fieldset>
  );
}

function LabelForm({ item, author, onSaved }) {
  const [category, setCategory] = useState(null);
  const [relevant, setRelevant] = useState(null);
  const [complexity, setComplexity] = useState(null);
  const [quality, setQuality] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const ready = category !== null && relevant !== null && complexity !== null && quality !== null;

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await postGoldenLabel({ project_id: item.id, author, category, relevant, complexity, quality });
      onSaved();
    } catch (cause) {
      setError(cause.message);
      setSaving(false);
    }
  }

  return (
    <form className="label-card" onSubmit={submit}>
      <h3>{item.title}</h3>
      <p className="muted">
        {item.budget_min ?? "—"}–{item.budget_max ?? "—"} {item.currency} · {item.project_type === "hourly" ? "por hora" : "precio fijo"}
      </p>
      <p className="post-text">{item.description}</p>
      <p className="muted">{item.skills.join(" · ")}</p>
      <Choice legend="Categoría" name="category" options={CATEGORIES} value={category} onChange={setCategory} />
      <Choice legend="¿Relevante?" name="relevant" options={RELEVANCE} value={relevant} onChange={setRelevant} />
      <Choice legend="Complejidad" name="complexity" options={COMPLEXITY} value={complexity} onChange={setComplexity} />
      <Choice legend="Calidad de la publicación" name="quality" options={QUALITY} value={quality} onChange={setQuality} />
      {error ? <p className="notice bad" role="alert">{error}</p> : null}
      <button className="primary" type="submit" disabled={!ready || saving}>
        {saving ? "Guardando…" : "Guardar y siguiente"}
      </button>
    </form>
  );
}

function Progress({ data }) {
  const done = data.label_pass === 2 ? data.done_pass2 : data.done_pass1;
  return (
    <>
      <p className="muted">
        Pasada {data.label_pass}: {done} de {data.total}
      </p>
      <progress max={data.total} value={done} aria-label={`Progreso de la pasada ${data.label_pass}`} />
    </>
  );
}

function Session({ author }) {
  const query = useApi(`/api/golden/next?author=${encodeURIComponent(author)}`);
  if (query.error) return <p className="notice bad" role="alert">{query.error}</p>;
  if (!query.data) return <p className="muted">Cargando…</p>;
  const data = query.data;
  if (data.status === "no_sample") return <p className="notice">Aún no se ha generado la muestra.</p>;
  if (data.status === "done") return <p className="notice">Has terminado las dos pasadas. Consulta el resultado abajo.</p>;
  if (data.status === "wait") {
    const date = new Date(data.available_at).toLocaleString("es", { dateStyle: "long", timeStyle: "short" });
    return (
      <p className="notice">
        Primera pasada terminada. La segunda se abre el <strong>{date}</strong>: esperar evita que respondas de memoria.
      </p>
    );
  }
  return (
    <>
      <Progress data={data} />
      <LabelForm key={`${data.label_pass}-${data.item.id}`} item={data.item} author={author} onSaved={query.reload} />
    </>
  );
}

function Comparison({ report, threshold }) {
  const title = report.same_person
    ? `${report.first.author}: pasada ${report.first.label_pass} frente a pasada ${report.second.label_pass}`
    : `${report.first.author} frente a ${report.second.author}`;
  return (
    <section>
      <h4>{title}</h4>
      <p className={`notice ${report.passes ? "" : "bad"}`}>
        {report.passes ? `Pasa: los cuatro campos alcanzan kappa ${formatKappa(threshold)}.` : `No pasa: algún campo queda por debajo de ${formatKappa(threshold)}. Revisa la rúbrica.`}
      </p>
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">Campo</th><th scope="col">Kappa</th><th scope="col">Coincidencia</th></tr></thead>
          <tbody>
            {Object.entries(FIELD_NAMES).map(([field, name]) => (
              <tr key={field}>
                <th scope="row">{name}</th>
                <td className="num">{formatKappa(report.kappa[field])}</td>
                <td className="num">{Math.round(report.raw_agreement[field] * 100)} %</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">Complejidad y calidad con pesos cuadráticos. Calidad sin pesos: {formatKappa(report.quality_unweighted_kappa)}.</p>
      <details>
        <summary>Desacuerdos ({report.disagreements.length})</summary>
        <div className="table-wrap">
          <table>
            <thead><tr><th scope="col">Proyecto</th><th scope="col">Campo</th><th scope="col">Primera</th><th scope="col">Segunda</th></tr></thead>
            <tbody>
              {report.disagreements.map((row) => (
                <tr key={`${row.project_id}-${row.field}`}>
                  <td className="value">{row.title}</td><td>{FIELD_NAMES[row.field]}</td>
                  <td>{formatAnswer(row.first)}</td><td>{formatAnswer(row.second)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function Agreement() {
  const query = useApi("/api/golden/agreement");
  if (!query.data) return null;
  return (
    <>
      <h3>Acuerdo</h3>
      {query.data.comparisons.length === 0
        ? <p className="muted">Se calcula al completar dos pasadas. Hasta entonces se oculta para no influir en tus respuestas.</p>
        : query.data.comparisons.map((report) => (
            <Comparison
              key={`${report.first.author}-${report.first.label_pass}-${report.second.author}-${report.second.label_pass}`}
              report={report} threshold={query.data.threshold}
            />
          ))}
    </>
  );
}

function Rubric() {
  const query = useApi("/api/golden/rubric");
  if (!query.data) return null;
  return (
    <details className="rubric">
      <summary>Rúbrica ({query.data.file})</summary>
      <div className="post-text">{query.data.text}</div>
    </details>
  );
}

export default function GoldenSet() {
  const [draft, setDraft] = useState(readAuthor);
  const [author, setAuthor] = useState(() => readAuthor().trim());

  function confirm(event) {
    event.preventDefault();
    const clean = draft.trim();
    saveAuthor(clean);
    setAuthor(clean);
  }

  return (
    <>
      <form className="filters" onSubmit={confirm}>
        <label>
          Tu nombre
          <input value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={80} required />
        </label>
        <button className="align-end" type="submit">Continuar</button>
      </form>
      <Rubric />
      {author ? <Session key={author} author={author} /> : <p className="notice">Escribe tu nombre para empezar a etiquetar.</p>}
      <Agreement />
    </>
  );
}
