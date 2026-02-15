#!/usr/bin/env python3
"""
Legacy compatibility models import path.

Kept for older tests/utilities expecting shoonya_platform.domain.models.
"""

from shoonya_platform.domain.business_models import AlertData, LegData

__all__ = ["AlertData", "LegData"]
