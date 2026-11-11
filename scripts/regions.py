"""Region a partir del codigo de pais, segun config/regiones.yaml."""
from functools import cache
from pathlib import Path

import yaml

from scripts.db import ROOT

REGIONS_PATH = ROOT / "config" / "regiones.yaml"
OTHER = "Otra"


@cache
def regions() -> dict[str, list[str]]:
    data = yaml.safe_load(Path(REGIONS_PATH).read_text(encoding="utf-8"))
    for region, codes in data.items():
        bad = [code for code in codes if not isinstance(code, str) or len(code) != 2]
        if bad:
            raise ValueError(f"Códigos no válidos en {region}: {bad}. Pon entre comillas valores como \"NO\".")
    return data


@cache
def _index() -> dict[str, str]:
    return {code: region for region, codes in regions().items() for code in codes}


def region_for(country: str | None) -> str | None:
    if not country:
        return None
    return _index().get(country.upper(), OTHER)


def countries_in(region: str) -> list[str]:
    return list(regions().get(region, []))


def market(client_country: str | None, currency_country: str | None) -> dict:
    """Pais y region para filtrar. Sin pais mencionado, se aproxima con el de la moneda."""
    if client_country:
        return {"country": client_country, "region": region_for(client_country), "approximate": False}
    return {"country": currency_country, "region": region_for(currency_country), "approximate": currency_country is not None}
