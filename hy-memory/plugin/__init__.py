"""
HY Memory Provider for Hermes Agent

第一梯队原生插件 — 实现 Hermes MemoryProvider 接口，
每次请求自动 prefetch 相关记忆注入 system prompt（100% 被动注入）。

安装：pip install hy-mem-internal
配置：~/.hermes/config.yaml → memory.provider: hy-memory
"""

__version__ = "0.2.7"

from .provider import HyMemoryProvider, register

__all__ = ["HyMemoryProvider", "register"]
