"""Tests del golden set: muestra, etiquetado a ciegas y acuerdo."""
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from dashboard.api import golden
from dashboard.api.main import app
from evals.kappa import weighted_kappa
from scripts import ingest
from scripts.golden_sample import build_sample, stratum
from tests.conftest import api_body, make_project, mock_client


def project(external_id="1", title="Trabajo", description="", skills=()):
    return {"source": "freelancer", "external_id": external_id, "title": title,
            "description": description, "skills": list(skills)}


def test_kappa_ponderado_premia_diferencias_pequenas():
    assert weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0
    assert weighted_kappa([3, 3], [3, 3]) == 1.0
    truth = [1, 2, 3, 4, 5] * 4
    near = [min(x + 1, 5) for x in truth]
    far = [6 - x for x in truth]
    assert weighted_kappa(truth, near) > 0.6 > weighted_kappa(truth, far)


@pytest.mark.parametrize("item,language,expected", [
    (project(skills=["SEO"]), "es", "idioma_es"),
    (project(skills=["SEO", "Internet Marketing"]), "en", "senal_seo"),
    (project(skills=["Google Analytics"]), "en", "senal_marketing"),
    (project(skills=["Zapier", "Marketing"]), "en", "senal_ia"),
    (project(skills=["WordPress"]), "en", "senal_web"),
    (project(skills=["Figma"]), "en", "senal_ux"),
    (project(title="App that needs good SEO", skills=["PHP"]), "en", "negativo_dificil"),
    (project(title="Logo with a UX touch", skills=["Logo Design"]), "en", "negativo_dificil"),
    (project(title="Video edit", skills=["Video Editing"]), "en", "sin_senal"),
    (project(title="Build a guide tool", skills=["PHP"]), "en", "sin_senal"),
])
def test_estratos(item, language, expected):
    assert stratum(item, language) == expected


def test_muestra_es_determinista_y_respeta_el_total():
    items = [project(str(i), skills=["SEO"] if i % 2 else ["PHP"]) for i in range(300)]
    first = build_sample(items, {}, "v1", total=100)
    assert first == build_sample(list(reversed(items)), {}, "v1", total=100)
    assert len(first["items"]) == 100
    assert len({i["external_id"] for i in first["items"]}) == 100
    assert {i["split"] for i in first["items"]} == {"dev", "test"}


def labels_for(answer="seo", relevant=True, complexity="media", quality=4):
    return {"category": answer, "relevant": relevant, "complexity": complexity, "quality": quality}


@pytest.fixture
def api(conn, config, monkeypatch, tmp_path):
    """Tres proyectos ingeridos y una muestra de prueba sobre ellos."""
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    cfg = config()
    client = mock_client(lambda r: httpx.Response(200, json=api_body([make_project(i) for i in (1, 2, 3)])))
    ingest.run_ingest(conn, "freelancer", client=client, **cfg)
    conn.commit()
    (tmp_path / "rubrica_v2.md").write_text("# Rubrica", encoding="utf-8")
    (tmp_path / "sample_v2.json").write_text(json.dumps({
        "version": "v2", "rubric": "rubrica_v2.md", "min_days_between_passes": 7,
        "items": [{"source": "freelancer", "external_id": str(i), "stratum": "x", "split": "dev"} for i in (1, 2, 3)],
    }), encoding="utf-8")
    monkeypatch.setattr(golden, "GOLDEN_DIR", tmp_path)
    return TestClient(app), conn


def label_all(client, author="Ana", **answers):
    """Etiqueta hasta terminar la pasada abierta y devuelve lo guardado en orden."""
    seen = []
    while True:
        body = client.get("/api/golden/next", params={"author": author}).json()
        if body["status"] != "label":
            return seen, body
        seen.append(body["item"]["id"])
        response = client.post("/api/golden/labels", json={
            "project_id": body["item"]["id"], "author": author, **labels_for(**answers)})
        assert response.status_code == 201


def unlock_second_pass(conn):
    conn.execute("UPDATE labels SET created_at = created_at - interval '8 days'")
    conn.commit()


def test_sin_muestra_lo_indica(api, monkeypatch, tmp_path):
    client, _ = api
    monkeypatch.setattr(golden, "GOLDEN_DIR", tmp_path / "vacio")
    assert client.get("/api/golden/next", params={"author": "ana"}).json() == {"status": "no_sample"}


def test_primera_pasada_guarda_tres_etiquetas_con_division(api):
    client, conn = api
    seen, body = label_all(client)
    assert len(seen) == 3 and body["status"] == "wait" and body["done_pass1"] == 3
    conn.rollback()
    rows = conn.execute("SELECT field, author, dataset_split, label_pass, golden_version FROM labels").fetchall()
    assert len(rows) == 12
    assert {r["field"] for r in rows} == {"category", "relevant", "complexity", "quality"}
    assert {(r["author"], r["dataset_split"], r["label_pass"], r["golden_version"]) for r in rows} == {("ana", "dev", 1, "v2")}


def test_segunda_pasada_bloqueada_hasta_cumplir_el_plazo(api):
    client, conn = api
    _, body = label_all(client)
    assert body["item"] is None and body["available_at"] is not None
    response = client.post("/api/golden/labels", json={"project_id": 1, "author": "ana", **labels_for()})
    assert response.status_code == 409
    conn.rollback()
    unlock_second_pass(conn)
    assert client.get("/api/golden/next", params={"author": "ana"}).json()["label_pass"] == 2


def test_segunda_pasada_es_a_ciegas(api):
    client, conn = api
    label_all(client)
    conn.rollback()
    unlock_second_pass(conn)
    body = client.get("/api/golden/next", params={"author": "ana"}).json()
    text = json.dumps(body)
    assert "expected_value" not in text and "category" not in text and "quality" not in text
    assert client.get("/api/golden/agreement").json()["comparisons"] == []


def test_no_se_repite_etiqueta_ni_se_admite_fuera_de_muestra(api):
    client, conn = api
    item = client.get("/api/golden/next", params={"author": "ana"}).json()["item"]
    body = {"project_id": item["id"], "author": "ana", **labels_for()}
    assert client.post("/api/golden/labels", json=body).status_code == 201
    assert client.post("/api/golden/labels", json=body).status_code == 409
    assert client.post("/api/golden/labels", json={**body, "project_id": 999999}).status_code == 422
    assert client.post("/api/golden/labels", json={**body, "quality": 6}).status_code == 422
    assert client.post("/api/golden/labels", json={**body, "category": "ambas"}).status_code == 422
    assert client.post("/api/golden/labels", json={**body, "complexity": "extrema"}).status_code == 422


def test_origen_externo_no_puede_etiquetar(api):
    client, _ = api
    response = client.post("/api/golden/labels", headers={"origin": "https://evil.example"},
                           json={"project_id": 1, "author": "ana", **labels_for()})
    assert response.status_code == 403


def test_acuerdo_misma_persona_tras_dos_pasadas(api):
    client, conn = api
    label_all(client)
    conn.rollback()
    unlock_second_pass(conn)
    label_all(client, quality=3)
    assert client.get("/api/golden/next", params={"author": "ana"}).json()["status"] == "done"
    comparison = client.get("/api/golden/agreement").json()["comparisons"][0]
    assert comparison["same_person"] is True and comparison["n"] == 3
    assert comparison["raw_agreement"] == {"category": 1.0, "relevant": 1.0, "complexity": 1.0, "quality": 0.0}
    assert len(comparison["disagreements"]) == 3 and comparison["disagreements"][0]["title"]


def test_acuerdo_entre_dos_personas_sin_esperar_plazo(api):
    client, conn = api
    label_all(client, author="ana")
    label_all(client, author="bea", answer="otra")
    comparison = client.get("/api/golden/agreement").json()["comparisons"][0]
    assert comparison["same_person"] is False and comparison["raw_agreement"]["category"] == 0.0
    assert comparison["first"] == {"author": "ana", "label_pass": 1}


def test_nombre_se_normaliza(api):
    client, _ = api
    item = client.get("/api/golden/next", params={"author": "Ana"}).json()["item"]
    client.post("/api/golden/labels", json={"project_id": item["id"], "author": "  ANA ", **labels_for()})
    assert client.get("/api/golden/next", params={"author": "ana"}).json()["done_pass1"] == 1


def test_rubrica_disponible(api):
    client, _ = api
    assert client.get("/api/golden/rubric").json() == {"file": "rubrica_v2.md", "text": "# Rubrica"}
