# Hermes Evolution Hub

Hermes Dashboard plugin — Cognitive OS architecture, decision ledger, and runtime observability.

适用于 Hermes Agent Dashboard 的插件 tab，用于展示 Hermes 架构图、Cognitive OS 决策账本、审查队列与系统健康状态。

## Architecture Audits

- [Codex 与 Hermes Agent 执行层对比](docs/agent-execution-layer-comparison.md)
- [Evolution Hub 架构图审计](docs/evolution-architecture-audit.md)

## Structure

```text
evolution-hub/
├── README.md
├── dashboard/                  # Hermes Dashboard plugin
│   ├── manifest.json           # Plugin manifest
│   ├── plugin_api.py           # Backend API (FastAPI router)
│   ├── dist/
│   │   ├── index.js            # Frontend React bundle
│   │   └── style.css           # Frontend styles
│   └── ...
└── evolution_hub/              # Static assets
    └── architecture.svg        # SVG architecture diagram
```

## Dependencies

- **Hermes Agent** with Dashboard plugin support
- **Cognitive OS SQLite ledger**, resolved from `COGNITIVE_OS_DB` or `~/projects/cognitive-os/data/cognitive.db`

## Installation

Copy this repo to `~/.hermes/plugins/evolution-hub/` or create a symlink, then restart the Hermes Dashboard.

```bash
ln -s /path/to/your/evolution-hub ~/.hermes/plugins/evolution-hub
hermes dashboard --host 0.0.0.0 --port 9119 --insecure --skip-build
```

Then open the Dashboard and navigate to the "进化中枢" tab.

## Runtime Data

The plugin backend is mounted by Hermes Dashboard at:

```text
/api/plugins/hermes-evolution-hub/
```

Main views read:

- Cognitive OS ledger tables such as `evidence`, `claims`, `models`, `decisions`, `intents`, and `outcomes`
- maintenance inbox data from `maintenance_issues`, `proposals`, and `projection_state`
- Hermes runtime logs from `~/.hermes/logs/agent.log`
- plugin architecture metadata from `dashboard/dist/architecture.json` and backend `/api/architecture`

The review surfaces are read-only. They do not accept proposals, mutate ledger rows, or automatically repair data.

## Notes

- The React bundle is pre-built; edit `dashboard/dist/index.js` directly when changing the UI.
- The SVG architecture diagram is instance-specific and may need regeneration if the runtime architecture changes.
- Source-path lookup is local-environment aware and can be influenced with `HERMES_SOURCE_BASE`.
