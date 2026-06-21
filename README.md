# Hermes Evolution Hub

Hermes Dashboard plugin — architecture diagram + HY Memory evolution visualization.

适用于 Hermes Agent Dashboard 的插件 tab，展示架构图、HY Memory 进化引擎状态与系统健康度。

## Structure

```
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

- **Hermes Agent** (0.16+)
- **hy-memory** SDK — install separately:
  ```bash
  pip install hy-memory
  ```
  Or follow the [HY Memory setup guide](https://hermesagent.org.cn/docs/developer-guide/memory-provider-plugin).

## Installation

### Quick install (AI-assisted)

Copy this repo to `~/.hermes/plugins/evolution-hub/` (or create a symlink),
then restart the Hermes Dashboard.

```bash
# Symlink from your local repo
ln -s /path/to/your/evolution-hub ~/.hermes/plugins/evolution-hub

# Restart dashboard
hermes dashboard --host 0.0.0.0 --port 9119 --insecure --skip-build
```

### Manual setup

1. Ensure `hy-memory` is installed (`pip install hy-memory`)
2. Copy or symlink this directory to `~/.hermes/plugins/evolution-hub/`
3. Restart the Hermes Dashboard
4. Open the Dashboard and navigate to the "进化中枢" tab

## Notes

- The `plugin_api.py` paths are relative and should work on any Hermes installation
- The SVG architecture diagram (`evolution_hub/architecture.svg`) is **instance-specific** — you may want to generate your own
- The React bundle (`dist/index.js`) is pre-built. To modify the UI, edit `dashboard/dist/index.js` directly, or rebuild from source

## Memory provider precedence

When both the built-in `memory_tool` (local `MEMORY.md` / `USER.md`) and an external memory provider (e.g. HY Memory) are active, the system prompt is assembled as follows:

```
stable system prompt
context files
local memory block
local user profile block
external memory provider block   <-- HY Memory content goes here
timestamp / model / provider info
```

HY Memory does **not** override the local memory block — it is **appended after it**. In practice, because the HY block is closer to the end of the prompt, the model usually weights it more heavily when the two sources conflict.

## Customization

Ask your AI assistant to:
- Update `dist/index.js` colors to match your Dashboard theme
- Replace `architecture.svg` with your own Hermes architecture
- Add/remove nodes in the NODES map in `dist/index.js`
