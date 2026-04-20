"""Shared router instance for workflow API."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])
