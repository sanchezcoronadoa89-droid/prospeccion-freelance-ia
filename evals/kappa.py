"""Kappa de Cohen entre dos etiquetadores o dos pasadas.
Uso: python -m evals.kappa archivo.csv columna_a columna_b
"""
import csv
import sys
from collections import Counter


def cohen_kappa(a: list, b: list) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("Se necesitan dos listas no vacias de igual longitud")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[k] * count_b[k] for k in count_a) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def weighted_kappa(a: list[int], b: list[int], scale: tuple[int, int] = (1, 5)) -> float:
    """Kappa con pesos cuadraticos: para escalas ordenadas, un 4 frente a un 5 penaliza poco."""
    if len(a) != len(b) or not a:
        raise ValueError("Se necesitan dos listas no vacias de igual longitud")
    low, high = scale
    span = (high - low) ** 2
    n = len(a)
    observed = sum((x - y) ** 2 for x, y in zip(a, b)) / (n * span)
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[i] * count_b[j] * (i - j) ** 2 for i in count_a for j in count_b) / (n * n * span)
    return 1.0 if expected == 0 else 1 - observed / expected


if __name__ == "__main__":
    path, col_a, col_b = sys.argv[1:4]
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    value = cohen_kappa([r[col_a] for r in rows], [r[col_b] for r in rows])
    print(f"kappa={value:.3f} n={len(rows)} {'PASA' if value >= 0.6 else 'NO PASA'} (umbral 0,6)")
