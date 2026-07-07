# -*- coding: utf-8 -*-
"""
HY Memory CLI for Hermes — `hermes hy-memory <subcommand>`

子命令：
  doctor          连通性 + 配置体检（不写不删，只读）
  add <text>      手动写入一条记忆
  search <query>  手动搜索
  list            列出最近 N 条记忆

Hermes 在 plugin 加载时调用 register_cli(subparser) 把以上 subcommand
挂到 hermes 主 CLI 上；只有当 provider 已配置（HY_MEMORY_USER_ID 设置）
时才激活。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional


def _add_subcommands(sub: argparse._SubParsersAction) -> None:
    """Attach init / doctor / add / search / list / reset onto a subparsers action.

    Shared by both entry points so the command set stays identical:
      - Hermes main CLI:  `hermes hy-memory <cmd>`   (via register_cli)
      - standalone:       `hermes-hy-memory <cmd>`   (via _main_standalone)
    """
    p_init = sub.add_parser("init", help="Interactive setup wizard (writes ~/.hermes/.env)")
    p_init.set_defaults(func=_cmd_init)

    p_install = sub.add_parser(
        "install",
        help="Activate the plugin in Hermes (symlink into ~/.hermes/plugins + ensure SDK in Hermes' venv)",
    )
    p_install.add_argument(
        "--hermes-python",
        help="Path to the Python that Hermes runs (auto-detected from the `hermes` launcher if omitted)",
    )
    p_install.add_argument(
        "--copy", action="store_true",
        help="Copy plugin files instead of symlinking (goes stale on upgrade)",
    )
    p_install.add_argument(
        "--no-sdk", action="store_true",
        help="Skip installing the hy-memory SDK into Hermes' venv (only link the plugin dir)",
    )
    p_install.add_argument(
        "-U", "--upgrade", action="store_true",
        help="Force reinstall/upgrade the plugin in Hermes' venv even if a version is already present",
    )
    p_install.set_defaults(func=_cmd_install)

    p_doctor = sub.add_parser("doctor", help="Health check (read-only diagnostic)")
    p_doctor.set_defaults(func=_cmd_doctor)

    p_add = sub.add_parser("add", help="Manually add a memory")
    p_add.add_argument("text", help="Memory content")
    p_add.add_argument("--user-id", help="Override HY_MEMORY_USER_ID")
    p_add.add_argument("--agent-id", help="Override HY_MEMORY_AGENT_ID")
    p_add.set_defaults(func=_cmd_add)

    p_search = sub.add_parser("search", help="Search memories")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--user-id", help="Override HY_MEMORY_USER_ID")
    p_search.add_argument("--agent-id", help="Override HY_MEMORY_AGENT_ID")
    p_search.set_defaults(func=_cmd_search)

    p_list = sub.add_parser("list", help="List recent memories")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--user-id", help="Override HY_MEMORY_USER_ID")
    p_list.add_argument("--agent-id", help="Override HY_MEMORY_AGENT_ID")
    p_list.set_defaults(func=_cmd_list)

    p_reset = sub.add_parser(
        "reset",
        help="Delete stored memories for a user (DESTRUCTIVE)",
    )
    p_reset.add_argument("--user-id", help="Override HY_MEMORY_USER_ID")
    p_reset.add_argument("--agent-id", help="Override HY_MEMORY_AGENT_ID")
    p_reset.add_argument(
        "--all-agents", action="store_true",
        help="Delete across ALL agents for this user (default: only the current agent)",
    )
    p_reset.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip the confirmation prompt",
    )
    p_reset.set_defaults(func=_cmd_reset)


def register_cli(subparser: argparse._SubParsersAction) -> None:
    """
    Hermes 插件 CLI 注册入口。

    会被 hermes 主 CLI 在加载插件时调用：
        ` hermes hy-memory init / doctor / add / search / list `
    """
    p = subparser.add_parser(
        "hy-memory",
        help="HY Memory plugin CLI (init / doctor / add / search / list)",
    )
    sub = p.add_subparsers(dest="hy_memory_cmd", required=True)
    _add_subcommands(sub)


# ================================================================
# Helpers
# ================================================================

def _load_hermes_env() -> None:
    """Load ~/.hermes/.env into os.environ (does NOT override existing vars).

    The standalone `hermes-hy-memory` binary runs outside the Hermes daemon, so
    nothing has loaded the .env the wizard wrote. Without this, doctor/add/
    search/list see HY_MEMORY_USER_ID as unset even though `init` saved it.
    Real shell env wins over the file (override=False) so explicit exports and
    --flags still take precedence.
    """
    env_path = os.path.join(os.path.expanduser("~"), ".hermes", ".env")
    if not os.path.isfile(env_path):
        return
    try:
        from dotenv import load_dotenv  # transitive via hy-memory
        load_dotenv(env_path, override=False)
    except Exception:
        # best-effort minimal parser if python-dotenv is unavailable
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key, val = key.strip(), val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val
        except Exception:
            pass


def _resolve_ids(args) -> tuple[str, str, str]:
    """从 args + env 解析 user_id / agent_id / mode（顺序：CLI flag > env）"""
    _load_hermes_env()
    user_id = (getattr(args, "user_id", None) or os.environ.get("HY_MEMORY_USER_ID", "")).strip()
    agent_id = (getattr(args, "agent_id", None) or os.environ.get("HY_MEMORY_AGENT_ID", "hermes")).strip() or "hermes"
    mode = os.environ.get("HY_MEMORY_MODE", "pro").strip() or "pro"
    return user_id, agent_id, mode


def _make_client(mode: str):
    try:
        from . import home as H
        from . import server_manager as SM
        H.apply_memory_data_dir()
        auto_start = os.environ.get("HY_MEMORY_AUTO_START_SERVER", "true").lower() not in (
            "0", "false", "no",
        )
        ok, url = SM.ensure_server(auto_start=auto_start)
        if ok:
            from .http_client import HttpMemoryClient
            return HttpMemoryClient(url)
    except ImportError:
        pass
    try:
        from . import home as H
        H.apply_memory_data_dir()
        from hy_memory import HyMemoryClient
    except ImportError as e:
        print(f"ERROR: hy-memory SDK not installed: {e}", file=sys.stderr)
        print("Hint: pip install hy-memory", file=sys.stderr)
        sys.exit(2)
    try:
        return HyMemoryClient(mode=mode)
    except Exception as e:
        print(f"ERROR: HyMemoryClient init failed: {e}", file=sys.stderr)
        sys.exit(2)


def _print_kv(label: str, value, ok: Optional[bool] = None) -> None:
    """[ok]/[fail]/[--] label: value"""
    if ok is True:
        prefix = "  ✓ "
    elif ok is False:
        prefix = "  ✗ "
    else:
        prefix = "    "
    print(f"{prefix}{label}: {value}")


# ================================================================
# Subcommands
# ================================================================

def _check_url(url: str, path: str = "") -> bool:
    """Best-effort connectivity probe (3s)."""
    try:
        import urllib.request
        target = url.rstrip("/") + path
        with urllib.request.urlopen(target, timeout=3) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def _cmd_init(args) -> int:
    """Interactive 4-step setup wizard → writes ~/.hermes/.env.

    Mirrors the OpenClaw init wizard (same providers / default models / dims).
    """
    try:
        import questionary
    except ImportError:
        print("ERROR: questionary not installed. Run: pip install questionary", file=sys.stderr)
        return 2

    try:
        from .init_wizard import (
            LLM_PROVIDERS, EMBEDDER_PROVIDERS, VECTOR_PROVIDERS, KNOWN_EMBEDDER_DIMS,
            build_llm_env, build_embedder_env, build_vector_env,
            write_env_file, default_hermes_env_path, default_user_id,
            set_memory_provider, default_hermes_config_path,
        )
    except ImportError:
        # standalone invocation (folder-drop / python cli.py) — no package context
        from init_wizard import (  # type: ignore
            LLM_PROVIDERS, EMBEDDER_PROVIDERS, VECTOR_PROVIDERS, KNOWN_EMBEDDER_DIMS,
            build_llm_env, build_embedder_env, build_vector_env,
            write_env_file, default_hermes_env_path, default_user_id,
            set_memory_provider, default_hermes_config_path,
        )

    print("🧠 HY Memory for Hermes — Interactive Setup\n")

    # ── Step 1/4: LLM ───────────────────────────────────────────────────
    llm_id = questionary.select(
        "Step 1/4: LLM provider (memory extraction & reasoning)",
        choices=[questionary.Choice(f"{p.label}  ({p.default_model})", value=p.id) for p in LLM_PROVIDERS],
    ).ask()
    if llm_id is None:
        print("Cancelled."); return 0
    llm_def = next(p for p in LLM_PROVIDERS if p.id == llm_id)

    llm_key = None
    llm_url = None
    if llm_def.needs_api_key:
        llm_key = questionary.password(f"{llm_def.label} API Key").ask()
        if not llm_key:
            print("Cancelled (API key required)."); return 0
    if llm_def.needs_url:
        llm_url = questionary.text("API URL", default=llm_def.default_url or "").ask()
        if llm_id == "ollama" and llm_url and not _check_url(llm_url.replace("/v1", ""), "/api/tags"):
            print(f"  ⚠ Cannot reach Ollama at {llm_url} (continuing anyway)")
    llm_model = questionary.text("Model", default=llm_def.default_model).ask() or llm_def.default_model
    llm_env = build_llm_env(llm_id, api_key=llm_key, model=llm_model, url=llm_url)

    # ── Step 2/4: Embedder ──────────────────────────────────────────────
    emb_id = questionary.select(
        "Step 2/4: Embedding provider",
        choices=[questionary.Choice(f"{p.label}  ({p.default_model}, {p.default_dims}d)", value=p.id) for p in EMBEDDER_PROVIDERS],
    ).ask()
    if emb_id is None:
        print("Cancelled."); return 0
    emb_def = next(p for p in EMBEDDER_PROVIDERS if p.id == emb_id)

    emb_key = None
    emb_url = None
    if emb_def.needs_api_key:
        reuse = bool(llm_key) and (
            (emb_id == "openai" and llm_id == "openai")
            or (emb_id == "gemini" and llm_id == "google")
            or (emb_id == "moonshot" and llm_id == "moonshot")
        )
        emb_key = questionary.password(
            f"{emb_def.label} API Key" + (" (enter to reuse LLM key)" if reuse else "")
        ).ask()
        if not emb_key and reuse:
            emb_key = llm_key
        if not emb_key:
            print("Cancelled (API key required)."); return 0
    if emb_def.needs_url:
        emb_url = questionary.text("API URL", default=emb_def.default_url or "").ask()
    emb_model = questionary.text("Embedding model", default=emb_def.default_model).ask() or emb_def.default_model
    known_dims = KNOWN_EMBEDDER_DIMS.get(emb_model, emb_def.default_dims)
    dims_str = questionary.text(
        "Embedding dimensions", default=str(known_dims),
        validate=lambda v: (v.isdigit() and int(v) > 0) or "Must be a positive integer",
    ).ask()
    if dims_str is None:
        print("Cancelled."); return 0
    emb_env = build_embedder_env(emb_id, api_key=emb_key, model=emb_model, url=emb_url, dims=int(dims_str))

    # ── Step 3/4: Vector store ──────────────────────────────────────────
    vs_id = questionary.select(
        "Step 3/4: Vector store",
        choices=[questionary.Choice(f"{p.label}  ({'requires server' if p.needs_connection else 'no setup'})", value=p.id) for p in VECTOR_PROVIDERS],
    ).ask()
    if vs_id is None:
        print("Cancelled."); return 0
    vs_def = next(p for p in VECTOR_PROVIDERS if p.id == vs_id)
    if vs_id == "qdrant":
        host = questionary.text("Qdrant host", default="localhost").ask() or "localhost"
        port = questionary.text("Qdrant port", default="6333").ask() or "6333"
        vs_env = build_vector_env("qdrant", host=host, port=int(port))
        if not _check_url(f"http://{host}:{port}", "/healthz"):
            print(f"  ⚠ Cannot reach Qdrant at http://{host}:{port}")
            if vs_def.setup_hint:
                print(f"    Quick start: {vs_def.setup_hint}")
    else:
        vs_env = build_vector_env(vs_id)

    # ── Step 4/4: userId ────────────────────────────────────────────────
    # Mode is not asked: default to "pro" (LLM extract + evolution — the only
    # sensible default for passive recall; `lite` can't be recalled). Power
    # users can change HY_MEMORY_MODE in ~/.hermes/.env afterwards.
    mode = "pro"
    user_id = questionary.text("Step 4/4: User ID (memory namespace)", default=default_user_id()).ask()
    if not user_id:
        print("Cancelled."); return 0

    # ── Write ~/.hermes/.env ────────────────────────────────────────────
    env_updates = {
        "HY_MEMORY_USER_ID": user_id,
        "HY_MEMORY_AGENT_ID": "hermes",
        "HY_MEMORY_MODE": mode,
        # Route SDK logs (hy_memory.*) through Hermes' root logger so they show
        # up in `hermes logs` and follow its --level.
        "MEMORY_LOG_PROPAGATE": "true",
        **llm_env,
        **emb_env,
        **vs_env,
    }
    env_path = default_hermes_env_path()
    try:
        from . import home as H
        write_env_file(env_path, env_updates)
        H.write_config_snapshot(
            {"userId": user_id, "mode": mode, "agentId": "hermes", **env_updates},
            "hermes-hy-memory-init",
        )
    except Exception as e:
        print(f"ERROR: failed to write {env_path}: {e}", file=sys.stderr)
        print("\nSet these env vars manually:")
        for k, v in env_updates.items():
            shown = "***" if k.endswith("API_KEY") else v
            print(f"  export {k}={shown}")
        return 2

    print("\n✓ Configuration saved")
    print(f"  LLM:    {llm_def.label} ({llm_model})")
    print(f"  Embed:  {emb_def.label} ({emb_model}, {dims_str}d)")
    print(f"  Vector: {vs_def.label}")
    print(f"  Mode:   {mode}  (default; change HY_MEMORY_MODE in {env_path} to override)")
    print(f"  User:   {user_id}")
    print(f"  File:   {env_path}")
    print(f"  Home:   {H.HY_MEMORY_HOME}")

    # ── Activate the provider in ~/.hermes/config.yaml ──────────────────
    cfg_path = default_hermes_config_path()
    try:
        changed = set_memory_provider(cfg_path, "hy-memory")
        if changed:
            print(f"  Active: memory.provider = hy-memory  ({cfg_path})")
        else:
            print(f"  Active: memory.provider already = hy-memory  ({cfg_path})")
    except Exception as e:
        print(f"  ⚠ Could not set memory.provider automatically: {e}")
        print(f"    Edit {cfg_path} and add under `memory:`  provider: hy-memory")

    # ── Activate the plugin directory so Hermes can actually load it ─────
    # Hermes discovers memory providers by scanning ~/.hermes/plugins/<name>/
    # (NOT pip entry points), so a symlink there is required — otherwise
    # `hermes memory status` shows "NOT installed".
    print("\nLinking plugin into Hermes (~/.hermes/plugins/hy-memory)...")
    rc = _do_install(hermes_python=None, copy=False, no_sdk=False, quiet=False)
    if rc != 0:
        print("  ⚠ Auto-link failed — run `hermes-hy-memory install` manually.")

    print("\nSetup complete! Restart Hermes, then run `hermes-hy-memory doctor` to verify.")
    return 0


def _do_install(*, hermes_python: Optional[str], copy: bool,
                no_sdk: bool, upgrade: bool = False, quiet: bool = False) -> int:
    """Shared install logic for `install` subcommand + the tail of `init`.

    Steps:
      1. detect the Python Hermes runs under (its own venv),
      2. ensure the plugin package (+ hy-memory SDK) is installed AND current
         in that venv (unless --no-sdk),
      3. symlink (or copy) the package dir → ~/.hermes/plugins/hy-memory.
    Returns 0 on success, non-zero otherwise. Never raises.
    """
    try:
        from . import installer as I
    except ImportError:
        import installer as I  # type: ignore

    def say(msg: str) -> None:
        if not quiet:
            print(msg)

    # 1) locate Hermes' python
    py = I.detect_hermes_python(hermes_python)
    if py is None:
        say("  ✗ Could not find the Python that Hermes runs under.")
        say("    Re-run with: hermes-hy-memory install --hermes-python /path/to/hermes/venv/bin/python")
        # We can still link OUR package dir as a fallback (works if Hermes
        # shares this interpreter / site-packages).
        py = None

    # 2) ensure the PLUGIN PACKAGE *and* the hy-memory SDK are current in
    #    Hermes' venv. We always run an idempotent `-U` over BOTH packages
    #    rather than guessing the version direction from the CLI's own copy
    #    (which may be an editable dev install and mislead the compare). uv/pip
    #    no-ops when already latest, and crucially this also bumps the SDK —
    #    `-U <plugin>` alone leaves an already-"good enough" SDK dep untouched.
    if py is not None and not no_sdk:
        before_p = I.plugin_version(py)
        before_s = I.sdk_version(py)
        say(f"  • Ensuring latest in Hermes' venv ({py}) "
            f"[plugin={before_p or 'none'}, sdk={before_s or 'none'}] ...")
        try:
            cmd = I.install_into(py, upgrade=True)
            say(f"    ran: {' '.join(cmd)}")
            after_p = I.plugin_version(py)
            after_s = I.sdk_version(py)
            def _fmt(b, a):
                return f"{a}" + (f" (was {b})" if (b and b != a) else "")
            say(f"  • Hermes' venv now: plugin={_fmt(before_p, after_p)}, "
                f"sdk={_fmt(before_s, after_s)}")
        except Exception as e:
            say(f"  ⚠ Install into Hermes' venv failed: {e}")
            say("    Try manually, pointing at Hermes' Python:")
            say(f"      uv pip install --python {py} -U hermes-hy-memory hy-memory")

    # 3) resolve the package source dir and link it
    try:
        src = I.package_source_dir(py)  # py=None → our own location
    except Exception as e:
        say(f"  ✗ Cannot locate the hy_memory_hermes package: {e}")
        return 2

    link = I.plugin_link_path()
    try:
        if copy:
            import shutil
            if link.is_symlink() or link.exists():
                if link.is_dir() and not link.is_symlink():
                    shutil.rmtree(link)
                else:
                    link.unlink()
            link.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, link)
            say(f"  • Copied plugin → {link}")
        else:
            I.link_plugin(src, link, force=True)
            say(f"  • Linked {link} → {src}")
    except Exception as e:
        say(f"  ✗ Failed to place plugin dir at {link}: {e}")
        return 2

    return 0


def _cmd_install(args) -> int:
    """`hermes-hy-memory install` — make Hermes actually load the provider.

    pip alone does not activate a Hermes memory provider; Hermes scans
    ~/.hermes/plugins/<name>/. This links the installed package there and
    ensures the SDK lives in Hermes' venv.
    """
    print("HY Memory — install into Hermes")
    print("=" * 60)
    rc = _do_install(
        hermes_python=getattr(args, "hermes_python", None),
        copy=getattr(args, "copy", False),
        no_sdk=getattr(args, "no_sdk", False),
        upgrade=getattr(args, "upgrade", False),
        quiet=False,
    )
    if rc == 0:
        print("\n✓ Installed. Restart Hermes, then verify with:")
        print("    hermes memory status      # expect: Plugin: installed ✓")
        print("    hermes-hy-memory doctor   # SDK-side health check")
    else:
        print("\n✗ Install incomplete — see messages above.")
    return rc


def _cmd_doctor(args) -> int:
    """Health check — env, unified home, server reuse, list probe."""
    print("HY Memory Provider — Doctor")
    print("=" * 60)

    user_id, agent_id, mode = _resolve_ids(args)

    try:
        from . import home as H
        from . import server_manager as SM
    except ImportError:
        import home as H  # type: ignore
        import server_manager as SM  # type: ignore

    H.apply_memory_data_dir()

    # 1) Env vars
    print("\n[1/4] Environment")
    _print_kv("HY_MEMORY_USER_ID", user_id or "(unset)", ok=bool(user_id))
    _print_kv("HY_MEMORY_AGENT_ID", agent_id, ok=True)
    _print_kv("HY_MEMORY_MODE", mode, ok=mode in ("lite", "pro", "ultra"))

    embed_keys = [
        "OPENAI_API_KEY",
        "MEMORY_EMBEDDER_API_KEY",
        "AZURE_OPENAI_API_KEY",
    ]
    has_embed = any(os.environ.get(k) for k in embed_keys)
    _print_kv(
        "Embedder API key",
        "set" if has_embed else "(none of " + "/".join(embed_keys) + " set)",
        ok=has_embed,
    )

    print("\n[2/4] Unified home (~/.hy-memory/)")
    _print_kv("home", str(H.HY_MEMORY_HOME), ok=True)
    _print_kv("data (MEMORY_DATA_DIR)", os.environ.get("MEMORY_DATA_DIR", ""), ok=True)
    _print_kv("venv", str(H.VENV_DIR), ok=H.venv_layout_exists())
    _print_kv("config snapshot", str(H.CONFIG_JSON_PATH), ok=H.CONFIG_JSON_PATH.exists())

    if not user_id:
        print("\nFAIL: HY_MEMORY_USER_ID is required.", file=sys.stderr)
        return 2

    # 3) Server (reuse or bootstrap)
    print("\n[3/4] Server")
    auto_start = os.environ.get("HY_MEMORY_AUTO_START_SERVER", "true").lower() not in (
        "0", "false", "no",
    )
    ok, url = SM.ensure_server(auto_start=auto_start)
    _print_kv("HTTP server", url, ok=ok)
    if not ok:
        print("  (embedded client may still work if SDK is importable locally)")

    # 4) Client + list probe
    print("\n[4/4] Client init + list probe")
    try:
        client = _make_client(mode)
        _print_kv("backend", type(client).__name__, ok=True)
    except SystemExit:
        return 2
    except Exception as e:
        _print_kv("client", f"FAIL: {e}", ok=False)
        return 2

    try:
        result = client.list_memories(user_id=user_id, agent_id=agent_id, limit=1)
        vdb = result.get("vdb", {}) or {}
        total = vdb.get("total", 0)
        _print_kv(f"list_memories(user={user_id}, agent={agent_id})", f"total={total}", ok=True)
    except Exception as e:
        _print_kv("list_memories probe", f"FAIL: {e}", ok=False)
        client.close()
        return 2

    client.close()
    print("\nAll checks passed.")
    return 0


def _cmd_add(args) -> int:
    user_id, agent_id, mode = _resolve_ids(args)
    if not user_id:
        print("ERROR: HY_MEMORY_USER_ID required", file=sys.stderr)
        return 2

    client = _make_client(mode)
    try:
        result = client.add(
            args.text,
            user_id=user_id,
            agent_id=agent_id,
            session_id="hermes_cli",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("success") else 1
    finally:
        client.close()


def _flatten_memories(memories):
    """把 search() 返回统一拍平成 list。

    SDK search() chat 路径返回按通道分组的 dict
    {'profile': [...], 'proactive': [...], 'normal': [...]}；旧契约为扁平 list。
    三路 layer 互斥，无需去重；顺序 profile→proactive→normal。
    """
    if isinstance(memories, dict):
        out = []
        for ch in ("profile", "proactive", "normal"):
            out.extend(memories.get(ch) or [])
        return out
    return memories or []


def _cmd_search(args) -> int:
    user_id, agent_id, mode = _resolve_ids(args)
    if not user_id:
        print("ERROR: HY_MEMORY_USER_ID required", file=sys.stderr)
        return 2

    client = _make_client(mode)
    try:
        result = client.search(
            args.query,
            user_ids=[user_id],
            agent_ids=[agent_id],
            limit=args.limit,
        )
        memories = _flatten_memories(result.get("memories"))
        print(f"Found {len(memories)} memories for query={args.query!r}")
        for i, m in enumerate(memories, 1):
            score = m.get("score", 0)
            layer = m.get("layer", "")
            content = m.get("content", "")
            print(f"\n[{i}] score={score:.3f} layer={layer}")
            print(f"    {content}")
        return 0
    finally:
        client.close()


def _cmd_list(args) -> int:
    user_id, agent_id, mode = _resolve_ids(args)
    if not user_id:
        print("ERROR: HY_MEMORY_USER_ID required", file=sys.stderr)
        return 2

    client = _make_client(mode)
    try:
        result = client.list_memories(
            user_id=user_id, agent_id=agent_id, limit=args.limit,
        )
        vdb = result.get("vdb", {}) or {}
        memories = vdb.get("memories") or []
        total = vdb.get("total", 0)
        print(f"Listing {len(memories)}/{total} memories (user={user_id} agent={agent_id})")
        for i, m in enumerate(memories, 1):
            mid = m.get("memory_id", "")
            layer = m.get("layer", "")
            content = m.get("content", "")
            print(f"\n[{i}] {mid} layer={layer}")
            print(f"    {content}")
        return 0
    finally:
        client.close()


def _cmd_reset(args) -> int:
    """Delete stored memories for a user (DESTRUCTIVE).

    Scope:
      default        → only the current agent (HY_MEMORY_AGENT_ID, "hermes")
      --all-agents   → every agent under this user_id
    Requires confirmation unless -y/--yes is given.
    """
    user_id, agent_id, mode = _resolve_ids(args)
    if not user_id:
        print("ERROR: HY_MEMORY_USER_ID required", file=sys.stderr)
        return 2

    all_agents = getattr(args, "all_agents", False)
    scope = (
        f"ALL agents for user={user_id!r}"
        if all_agents
        else f"user={user_id!r} agent={agent_id!r}"
    )

    if not getattr(args, "yes", False):
        print(f"This will permanently delete memories: {scope}")
        try:
            answer = input("Type 'yes' to confirm: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    client = _make_client(mode)
    try:
        # agent_ids=None → all agents; [agent_id] → just this agent
        result = client.delete_all(
            user_id=user_id,
            agent_ids=None if all_agents else [agent_id],
        )
        deleted = result.get("deleted_count", 0)
        ok = result.get("success", False)
        print(f"{'Deleted' if ok else 'delete_all returned failure;'} "
              f"{deleted} memories ({scope})")
        return 0 if ok else 1
    finally:
        client.close()


# ================================================================
# Standalone entry — 当 plugin 不通过 hermes 加载时也能直接 python -m
# ================================================================

def _plugin_version() -> str:
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version("hermes-hy-memory")
        except PackageNotFoundError:
            return "unknown (not installed via pip)"
    except Exception:
        return "unknown"


def _main_standalone() -> int:
    # Single-level commands: `hermes-hy-memory init / doctor / add / search / list`
    parser = argparse.ArgumentParser(prog="hermes-hy-memory")
    parser.add_argument(
        "--version", "-V", action="version",
        version=f"hermes-hy-memory {_plugin_version()}",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_subcommands(sub)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(_main_standalone())
