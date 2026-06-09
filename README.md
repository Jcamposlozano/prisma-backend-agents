# Westfield Agent — Backend (Python)



- `GET /api/health` — estado + info del índice RAG.
- `POST /api/maia` — orquesta un turno del agente (con o sin OpenAI; ver fallback offline).

El shape JSON de las requests y responses es **idéntico al del Node**. El frontend (`Westfield_agent/src/`) puede apuntar a este servicio sin cambiar una línea de código — sólo hay que ajustar `VITE_API_PROXY_TARGET=http://localhost:8000` en `.env.local` del proyecto del front.

---

## Comandos

```bash
poetry install                 # crea venv e instala deps
cp .env.example .env           # editar OPENAI_API_KEY
make run-api                   # API en localhost:8000
make run-worker                # Worker (V1 stub no-op)
make test                      # pytest -v
make lint                      # ruff check
make format                    # ruff format + ruff check --fix
make docker-build              # construir imagen Docker
make docker-up                 # API + worker via docker compose
```

Sin Poetry instalado: `pip install poetry` o `pipx install poetry`.

---

## Layout

```
src/westfield_agent_back_python/
├── domain/         # entidades + tipos (no I/O)
│   ├── responses.py        # MaiaTurn, MaiaResponse, MaiaRequestBody
│   ├── rag.py              # RagIndex, RagChunk, AlwaysIncludeDoc
│   └── system_prompt.py    # SYSTEM_PROMPT (constante)
├── application/    # casos de uso
│   ├── ask_maia.py         # use case principal
│   ├── prompt_builder.py   # build_system_prompt(...)
│   ├── fallback.py         # respuestas plantilladas offline
│   └── sanitizers.py       # parser defensivo + anti-leak
├── ports/          # interfaces (Protocols)
│   ├── chat_client.py
│   └── retriever.py
├── adapters/       # implementaciones concretas
│   ├── openai_chat_client.py
│   ├── openai_embeddings.py
│   ├── cosine_retriever.py
│   └── index_file_loader.py
├── entrypoints/
│   ├── api.py              # FastAPI + composition root
│   └── worker.py           # stub no-op
└── shared/         # config, logger, shutdown, rate_limit
```

El `composition root` está en `entrypoints/api.py:_startup()`: lee la config, carga el índice, construye los adapters y los inyecta en el use case `AskMaia`. Para cambiar de OpenAI a otro provider basta con implementar `ports.chat_client.ChatClient` en `adapters/` y cambiar 3 líneas en `_startup()`. Los handlers HTTP no se enteran.

---

## Cómo se relaciona con el backend Node

| Pieza | Node | Python |
|---|---|---|
| HTTP | Hono | FastAPI |
| Puerto local | 3001 | 8000 |
| RAG retriever | cosine en memoria | cosine en memoria (con numpy) |
| Persistencia índice | `data/maia-index.json` | `data/maia-index.json` (copia) |
| Pipeline ingesta | `npm run ingest` | (no portado en V1) |
| Front | `Westfield_agent/src/` | mismo, ajustando `VITE_API_PROXY_TARGET` |

El servicio Python es **independiente** — vive en su propio repo (`git init`), tiene su propio `Dockerfile`, su propio puerto y sus propias env vars. Puede coexistir con el Node corriendo en paralelo durante una migración, o reemplazarlo del todo.

---

## RAG: generar y copiar el índice

El índice (`data/maia-index.json`, ~2 MB) se genera con la pipeline de ingesta del proyecto Node — que parsea PDF/DOCX y calcula embeddings con OpenAI:

```bash
cd ../Westfield_agent
npm run ingest                                # regenera data/maia-index.json
cp data/maia-index.json ../Westfield_agent_back_python/data/
```

Mientras el archivo no exista, Maia arranca **sin RAG**: opera con el prompt base + fallback offline. El healthcheck refleja `rag: null` en ese caso.

> En V2 se puede portar la ingesta a Python con `pypdf` + `python-docx` para evitar la dependencia del Node.

---

## Variables de entorno

| Var | Default | Notas |
|---|---|---|
| `OPENAI_API_KEY` | (sin default) | Sin esto, fallback offline. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Modelo de chat. |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Para retrieve por query. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Azure / proxies. |
| `MAIA_INDEX_PATH` | `./data/maia-index.json` | Path al índice. |
| `ENV` | `dev` | `dev` o `prod` → carga `configs/<env>.yaml`. |
| `LOG_LEVEL` | `INFO` | `DEBUG` muestra más en dev. |
| `HOST` | `0.0.0.0` | Bind del FastAPI. |
| `PORT` | `8000` | Puerto del FastAPI. |
| `WORKER_ENABLED` | `true` | Si `false`, `main_worker` sale al boot. |
| `WORKER_INTERVAL_SECONDS` | `10` | Cada cuántos segundos corre `tick()`. |
| `RATE_LIMIT_WINDOW` | `60` | Ventana en segundos del rate limit. |
| `RATE_LIMIT_MAX` | `12` | Max requests por IP por ventana. |

---

## Modo fallback offline

Si falta `OPENAI_API_KEY` o si OpenAI/embeddings fallan, `/api/maia` devuelve respuestas plantilladas (`FALLBACK_OPENINGS` + `FALLBACK_FOLLOWUPS`) con `fallback: true`. El frontend muestra un banner discreto pero la conversación sigue. Esto es intencional: el showcase no debe romperse en demos sin internet.

---

## Testing

```bash
make test                      # pytest -v
```

Cubre las piezas críticas sin tocar la red:

- `test_sanitizers.py` — parser defensivo, anti-leak, clamps.
- `test_fallback.py` — apertura, avance por turnos, alternancia opening/followup.
- `test_prompt_builder.py` — layout del system prompt + bloque `# Estado actual`.
- `test_cosine_retriever.py` — top-k, min_similarity, fallo de embedding.

No hay tests de integración contra OpenAI real — eso queda para QA manual con un POST a `/api/maia`.

---

