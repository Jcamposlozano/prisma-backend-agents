"""
Publica el prompt y/o config de un agente a S3 (fuente de verdad del runtime).

Flujo de actualización de un agente (ej. Maia), SIN redeploy:
  1. Editás los archivos locales versionados en  agents/<agent_id>/:
        - system.md    → el prompt del agente
        - config.json  → modelo, temperatura, hard_rules, etc.
  2. Corrés este script:  python scripts/publish_agent.py maia
  3. Se suben a  s3://<bucket>/<prefix>/<agent_id>/  (prompts/system.md + config.json).
  4. El runtime los toma al expirar su caché (REGISTRY_TTL_SECONDS, ~5 min):
     el front que llama a /api/v1/universities/<u>/agents/<agent_id>/chat ya
     recibe el comportamiento nuevo. NO hace falta reconstruir ni redesplegar
     la imagen — el prompt y el config viven en S3, no en el contenedor.

Para que el cambio se vea YA (sin esperar el TTL): reiniciá el servicio en AWS
(App Runner/ECS) — al arrancar, el caché está vacío y relee S3 al primer request.

Variables de entorno (de .env o del entorno):
  S3_BUCKET (requerido), AWS_REGION, UNIVERSITY_CODE (default: westfield),
  credenciales AWS estándar de boto3.

Uso:
  python scripts/publish_agent.py maia                # sube prompt + config
  python scripts/publish_agent.py maia --only prompt  # solo el prompt
  python scripts/publish_agent.py maia --only config  # solo el config
  python scripts/publish_agent.py maia --dry-run      # muestra qué subiría
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"


def main() -> int:
    parser = argparse.ArgumentParser(description="Publica prompt/config de un agente a S3.")
    parser.add_argument("agent_id", help="ID del agente (ej. maia).")
    parser.add_argument(
        "--only",
        choices=["prompt", "config"],
        help="Subir solo el prompt o solo el config (default: ambos).",
    )
    parser.add_argument("--dry-run", action="store_true", help="No sube; solo muestra.")
    args = parser.parse_args()

    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        print("ERROR: falta S3_BUCKET (ponelo en .env o en el entorno).", file=sys.stderr)
        return 1
    region = os.getenv("AWS_REGION", "us-east-1")
    university = os.getenv("UNIVERSITY_CODE", "westfield")
    prefix = f"org={university}/agents/{args.agent_id}"

    local = AGENTS_DIR / args.agent_id
    prompt_path = local / "system.md"
    config_path = local / "config.json"

    do_prompt = args.only in (None, "prompt")
    do_config = args.only in (None, "config")

    if do_prompt and not prompt_path.exists():
        print(f"ERROR: no existe {prompt_path}", file=sys.stderr)
        return 1
    if do_config and not config_path.exists():
        print(f"ERROR: no existe {config_path}", file=sys.stderr)
        return 1

    s3 = boto3.client("s3", region_name=region)

    if do_prompt:
        body = prompt_path.read_text(encoding="utf-8")
        key = f"{prefix}/prompts/system.md"
        print(f"prompt  -> s3://{bucket}/{key}  ({len(body)} chars)")
        if not args.dry_run:
            s3.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))

    if do_config:
        # Validar que sea JSON bien formado antes de subir.
        config = json.loads(config_path.read_text(encoding="utf-8"))
        key = f"{prefix}/config.json"
        print(
            f"config  -> s3://{bucket}/{key}  "
            f"(prompt_id={config.get('prompt_id')}, modelo={config.get('llm_model')})"
        )
        if not args.dry_run:
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8"),
            )

    if args.dry_run:
        print("\n(dry-run: no se subió nada)")
    else:
        print("\nOK. El runtime lo tomará al expirar el TTL (~5 min) o al reiniciar el servicio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
