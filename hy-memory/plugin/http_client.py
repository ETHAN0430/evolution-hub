# -*- coding: utf-8 -*-
"""Minimal HTTP client for HY Memory server (reuse OpenClaw/OpenCode server)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class HttpMemoryClient:
    """Subset of HyMemoryClient used by the Hermes provider over HTTP."""

    def __init__(self, base_url: str, *, timeout: float = 120.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._agent_id = os.environ.get("HY_MEMORY_AGENT_ID", "hermes").strip() or "hermes"
        self._session_id = "default_session"

    def close(self) -> None:
        return

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self._base}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}

    def search(
        self,
        query: str,
        *,
        user_ids: Optional[List[str]] = None,
        agent_ids: Optional[List[str]] = None,
        limit: int = 10,
        **_: Any,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "query": query,
            "user_ids": user_ids or [],
            "limit": limit,
        }
        if agent_ids:
            payload["agent_ids"] = agent_ids
        return self._request("POST", "/api/v1/search", payload)

    def add(
        self,
        data: Any,
        *,
        user_id: str,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "user_id": user_id,
            "agent_id": agent_id or self._agent_id,
            "session_id": session_id or self._session_id,
            "enable_agent": True,
        }
        if isinstance(data, str):
            payload["text"] = data
        else:
            payload["messages"] = data
        return self._request("POST", "/api/v1/add", payload)

    def delete(self, memory_id: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/api/v1/memories/{memory_id}")

    def list_memories(
        self,
        *,
        user_id: str,
        agent_id: Optional[str] = None,
        limit: int = 20,
        **_: Any,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "agent_id": agent_id or self._agent_id,
            "limit": limit,
        }
        return self._request("POST", "/api/v1/list", payload)

    def delete_all(
        self,
        *,
        user_id: str,
        agent_ids: Optional[List[str]] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"user_id": user_id}
        if agent_ids is not None:
            payload["agent_ids"] = agent_ids
        return self._request("POST", "/api/v1/delete_all", payload)
