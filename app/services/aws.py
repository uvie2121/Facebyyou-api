"""Lazy, cached AWS client/resource factories.

Centralizing boto3 construction keeps credential resolution in one place. In
production boto3 picks up the EC2 instance profile (IAM role) automatically; no
keys are ever passed in code.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3

from app.core.config import settings


@lru_cache
def s3_client() -> Any:
    return boto3.client("s3", region_name=settings.AWS_REGION)


@lru_cache
def dynamodb_resource() -> Any:
    kwargs: dict[str, Any] = {"region_name": settings.AWS_REGION}
    if settings.DYNAMODB_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.DYNAMODB_ENDPOINT_URL
    return boto3.resource("dynamodb", **kwargs)


@lru_cache
def secrets_client() -> Any:
    return boto3.client("secretsmanager", region_name=settings.AWS_REGION)
