# Agentes (fuente de verdad versionada)

Cada subcarpeta es un agente. Su **prompt y config viven en AWS S3** (de ahí los
lee el runtime); estos archivos son la **copia versionada en git**, editables.

```
agents/<agent_id>/
  system.md     # prompt del agente
  config.json   # modelo, temperatura, hard_rules, vector_store, etc.
```

## Cómo actualizar un agente (sin redeploy)

1. Editá `agents/<agent_id>/system.md` y/o `config.json`.
2. Publicá a S3:
   ```bash
   python scripts/publish_agent.py <agent_id>
   # o solo uno:  --only prompt   |   --only config
   # ver antes:   --dry-run
   ```
3. El runtime toma el cambio al expirar su caché (`REGISTRY_TTL_SECONDS`, ~5 min).
   El front que llama a `/api/v1/universities/<u>/agents/<agent_id>/chat` ya recibe
   el comportamiento nuevo. **No hace falta reconstruir ni redesplegar la imagen** —
   el prompt y el config no viven en el contenedor, viven en S3.

Para que el cambio se vea **al instante** (sin esperar el TTL): reiniciá el
servicio en AWS (App Runner / ECS). Al arrancar, el caché está vacío y relee S3.

## Verificar que quedó

```
GET https://<tu-dominio>/api/v1/universities/<u>/agents/<agent_id>/health
```
Devuelve `prompt_id`, `llm_model`, `vector_store_id` actuales — si coinciden con
tu `config.json`, el despliegue ya lo tomó. También devuelve `api_key`
(`"dedicada"` / `"global"`), para confirmar contra qué key factura el agente.

## Key dedicada (control de gastos)

Las API keys **no** van en `config.json` (viajaría a S3 y a la imagen). Van por env var,
con la convención `OPENAI_API_KEY_<AGENT_ID>` en mayúsculas y guiones → guión bajo:
`OPENAI_API_KEY_MAIA`, `OPENAI_API_KEY_STUDENT_SERVICES`, … Creando un proyecto de OpenAI
por agente, el dashboard separa el gasto de cada uno. El agente sin key propia usa la
global (`OPENAI_API_KEY`) y avisa con un `🟡` en el log al cargarse.

A diferencia del prompt y del config, **agregar o rotar una key sí requiere reiniciar el
servicio** — vive en el entorno, no en S3.

## Requisitos del entorno (`.env`)

`S3_BUCKET`, `AWS_REGION`, credenciales AWS (con permiso de escritura en el bucket),
y opcional `UNIVERSITY_CODE` (default `westfield`).
