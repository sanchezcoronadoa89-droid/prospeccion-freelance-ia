---
description: Ejecuta la ingesta de una fuente registrada, sin LLM
argument-hint: <fuente>
allowed-tools: Bash(.venv/Scripts/python -m scripts.ingest:*)
---

Ejecuta exactamente `.venv/Scripts/python -m scripts.ingest $ARGUMENTS` y resume el JSON de salida en pocas líneas.

- `no_ejecutada` (código 2): explica el motivo y remite a `specs/000-decision-fuente.md`. No cambies `legal_status` ni busques otra forma de acceder.
- `bloqueada`: informa y detente. No reintentes ni evadas el bloqueo.
- `cambio_estructura`: informa de que la corrida no pasa al análisis.
