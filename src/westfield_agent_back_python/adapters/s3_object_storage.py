"""
Adapter: storage de objetos sobre AWS S3 (boto3).

Implementa ObjectStorage (ver ports/object_storage.py). Las credenciales
las resuelve boto3 por su cadena estándar (env vars AWS_ACCESS_KEY_ID /
AWS_SECRET_ACCESS_KEY, perfil, rol IAM) — acá solo llegan bucket y región.

Es sync a propósito: el AgentRegistry lo envuelve en asyncio.to_thread y
solo lo invoca en cold-load / expiración de TTL.
"""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

from westfield_agent_back_python.domain.errors import ObjectNotFoundError

_NOT_FOUND_CODES = {"NoSuchKey", "404", "NoSuchBucket"}


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """
    Descompone "s3://bucket/path/al/objeto" en (bucket, key).

    raises ValueError si la URI no tiene el esquema s3:// o le falta el key.
    """
    if not uri.startswith("s3://"):
        raise ValueError(f"URI S3 inválida (esperaba s3://...): {uri!r}")
    rest = uri[len("s3://") :]
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError(f"URI S3 inválida (falta bucket o key): {uri!r}")
    return bucket, key


class S3ObjectStorage:
    """Implementa ObjectStorage contra un bucket fijo."""

    def __init__(self, *, bucket: str, region: str | None = None) -> None:
        if not bucket:
            raise ValueError("bucket S3 ausente — revisar config s3.bucket / S3_BUCKET.")
        self._bucket = bucket
        self._client = boto3.client("s3", region_name=region)

    @property
    def bucket(self) -> str:
        return self._bucket

    def get_bytes(self, key: str) -> bytes:
        try:
            res = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            if code in _NOT_FOUND_CODES:
                raise ObjectNotFoundError(f"s3://{self._bucket}/{key}") from err
            raise
        return res["Body"].read()

    def get_text(self, key: str) -> str:
        return self.get_bytes(key).decode("utf-8")

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return keys
