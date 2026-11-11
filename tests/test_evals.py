"""Tests de los evals de agentes. El modelo y la fuente son simulados."""
import json

import httpx
import pytest

from evals.run import relevance_metrics, run, score_to_scale, spearman
from scripts import ingest
from scripts.classify import run_classify
from tests.conftest import api_body, make_project, mock_client
from tests.test_agents import CONFIG, GOOD, SPEC, fake_runner


def test_spearman_y_empates():
    assert spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [30, 20, 10]) == pytest.approx(-1.0)
    assert spearman([1, 1, 2, 2], [1, 1, 2, 2]) == pytest.approx(1.0)
    assert spearman([1, 1], [1, 2]) is None
    assert score_to_scale(0) == 1 and score_to_scale(100) == 5


def test_metricas_de_relevancia():
    assert relevance_metrics([(True, True), (True, False), (False, True), (False, False)]) == {
        "relevant_precision": 0.5, "relevant_recall": 0.5}
    assert relevance_metrics([(False, False)]) == {"relevant_precision": None, "relevant_recall": None}


@pytest.fixture
def db(conn, config, monkeypatch):
    from dashboard.api import golden
    monkeypatch.setattr(golden, "load_sample", lambda: None)
    projects = [make_project(i, title=f"SEO audit {i}") for i in (1, 2, 3, 4)]
    client = mock_client(lambda r: httpx.Response(200, json=api_body(projects)))
    ingest.run_ingest(conn, "freelancer", client=client, **config())
    conn.commit()
    return conn


def test_eval_sin_datos_no_guarda_resultado(db, tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    result = run(db, "classify", "dev", results)
    assert result["n"] == 0 and not any(result["passes"].values()) and list(results.iterdir()) == []


def test_eval_detecta_regresion_contra_linea_base(db, tmp_path):
    run_classify(db, runner=fake_runner(), spec=SPEC, config=CONFIG)
    saved = db.execute("SELECT project_id FROM classifications ORDER BY id").fetchall()
    for field, value in (("category", GOOD["category"]), ("relevant", True)):
        for row in saved:
            db.execute(
                """INSERT INTO labels (project_id, field, expected_value, author, dataset_split, golden_version, label_pass)
                   VALUES (%s,%s,%s,'ana','dev','v2',1)""",
                (row["project_id"], field, json.dumps(value)),
            )
    first = run(db, "classify", "dev", tmp_path)
    assert first["n"] == 4 and first["metrics"]["relevant_recall"] == 1.0 and first["regressions"] == []
    assert first["passes"]["relevant_precision"] is True
    db.execute("UPDATE classifications SET relevance = 0.1 WHERE project_id = %s", (saved[0]["project_id"],))
    second = run(db, "classify", "dev", tmp_path)
    assert second["regressions"] == ["relevant_recall"]
    assert len(list(tmp_path.iterdir())) >= 1
