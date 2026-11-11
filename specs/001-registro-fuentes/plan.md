# 001 · Plan

- `config/sources.yaml` y `config/search_profiles.yaml` son la fuente de verdad, versionada en git.
- `scripts/registry.py` sincroniza la configuración con `sources` y `search_profiles` al inicio de cada ingesta. Un cambio en el hash de los criterios crea una versión nueva.
- `assert_source_allowed` es la puerta legal: se llama antes de crear el conector. No existe opción para forzarla.
- Cada fuente tiene un único perfil activo, garantizado por un índice único parcial; ese perfil puede agrupar varias búsquedas.
