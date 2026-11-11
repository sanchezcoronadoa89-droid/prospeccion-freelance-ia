import { useCallback, useEffect, useState } from "react";

async function request(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : `Error ${response.status}`;
    throw new Error(detail);
  }
  return body;
}

export function postLabel(projectId, label) {
  return request(`/api/projects/${projectId}/labels`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(label),
  });
}

export function postGoldenLabel(label) {
  return request("/api/golden/labels", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(label),
  });
}

export function postJson(path, body = {}) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Carga una ruta de la API y vuelve a cargarla cuando cambia. */
export function useApi(path) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!path) return undefined;
    let active = true;
    setState((current) => ({ ...current, loading: true, error: null }));
    request(path)
      .then((data) => active && setState({ data, error: null, loading: false }))
      .catch((error) => active && setState({ data: null, error: error.message, loading: false }));
    return () => {
      active = false;
    };
  }, [path, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, reload };
}
