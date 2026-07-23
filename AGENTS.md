# AGENTS.md

## Cursor Cloud specific instructions

### What this is
Single-file **Streamlit** ERP web app ("ERP Agrícola La Concepción") in `gemini-code-1778529434778.py` (Spanish UI). Data persists to a local SQLite file `erp_concepcion_v6.db` auto-created on first page load with seed users/data. There is no separate backend, DB server, or test suite.

### Running the app (only service)
Python deps install into the user site (`~/.local`), whose `bin` is not on `PATH`. Run via the module form so `PATH` doesn't matter:

```bash
python3 -m streamlit run gemini-code-1778529434778.py \
  --server.enableCORS false --server.enableXsrfProtection false --server.headless true
```

Serves on port `8501`. Seed admin login: `osvaldolira@laconcepcion.cl` / `9083` (other seed users: `secretaria@laconcepcion.cl` / `1111`). Some destructive actions also require master key `2908`.

### Non-obvious gotchas
- `requirements.txt` is unpinned, so pandas 3.x installs. pandas 3.x's `.style` accessor (used throughout the app) requires `jinja2 >= 3.1.5`; the OS ships an older `jinja2`, so a recent `jinja2` must be present in the user site or every table/dashboard view crashes with `The '.style' accessor requires jinja2`. The update script installs it.
- Google Drive backup (`pydrive2`/`gcp_service_account`) and Gmail SMTP login alerts are optional and gated behind `.streamlit/secrets.toml`; the app runs fully without them (sync/email are silently skipped).
- The `Compras > INSUMOS` tab's product selector only renders when inventory (Bodega) has products; use the `Compras > GASTOS VARIOS` tab to create a purchase without inventory.

### Lint / test / build
No linter config, no test suite, and no build step exist in this repo. "Running" is just launching the Streamlit app above.
