---
title: Visual Console GUI Extensibility & Micro-Frontends
description: Learn how to build and integrate custom GUI micro-frontends, navigation routes, and sidebar badges into the AgentV Visual Console without modifying core source code.
---

AgentV v1.7.3 features **Dynamic Navigation Manifest Ingestion** and **Runtime Module Federation** for the native Visual Console (`/v2`). 

This architecture allows Python plugins, third-party libraries, and enterprise extensions to inject custom tabs, sidebar entries, and interactive React micro-frontend views directly into the console **with zero build-time recompilation of the Open Core**.

---

## 🏛️ Architectural Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                   Python Backend (Plugin Layer)                  │
│                                                                  │
│  1. Plugin defines on_register_console_routes(app, nav_registry) │
│  2. Registers custom Flask API blueprints                        │
│  3. Appends NavItem metadata to app.config["NAV_REGISTRY"]       │
└────────────────────────────────┬─────────────────────────────────┘
                                 │
                                 │ GET /api/nav (JSON Manifest)
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│             Visual Console (Open Core React Frontend)            │
│                                                                  │
│  1. Ingests Manifest on mount via TanStack Query (60s staleTime) │
│  2. Merges dynamic items with fallback built-in groups           │
│  3. Renders Badges ("LIVE", "APM", "CUSTOM"), Tiers, & Icons     │
│  4. Mounts remote ESM bundles on demand via React.lazy & import()│
│  5. Fault-isolated inside RemoteErrorBoundary                    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 📋 Navigation Manifest Schema

When your plugin appends navigation metadata to `nav_registry`, it conforms to the following schema:

```typescript
export interface NavItem {
  id?: string;                  // Unique identifier (e.g. "fleet_monitor")
  name: string;                 // Display label in the sidebar
  path: string;                 // Route path (e.g. "/fleet") or external URL ("https://...")
  icon?: string;                // Lucide icon name (e.g. "Cpu", "Layers", "Radio", "Terminal")
  group?: string;               // Target nav group (e.g. "Operations", "Audit & Compliance", "Build")
  badge?: string;               // Optional badge chip (e.g. "LIVE", "HOT-RELOAD", "FLEET", "CUSTOM")
  tier?: 'core' | 'enterprise'; // Visual tier accent (amber accent for 'enterprise')
  remoteEntry?: string;         // ESM bundle URL for dynamic micro-frontend mounting
  required_role?: string[];     // Optional RBAC restrictions (e.g. ["System Admin"])
}
```

### Supported Icon Identifiers
The console's dynamic icon resolver automatically maps standard icon string keys to Lucide icons:
- `home`, `filetext`, `play`, `activity`, `barchart`, `shield`, `shieldcheck`, `settings`, `bookopen`, `server`, `bell`, `heartpulse`, `layers`, `cpu`, `radio`, `terminal`, `zap`, `compass`, `sparkles`
- Any unknown or unspecified icon gracefully defaults to `chevronright`.

---

## 🛠️ Step-by-Step Guide: Building a GUI Extension

### Step 1: Register Console Routes in Python Plugin

In your Python plugin class (inheriting from `BaseEvalPlugin`), implement `on_register_console_routes`:

```python
from eval_runner.plugins import BaseEvalPlugin
from flask import Blueprint, jsonify, send_from_directory
from pathlib import Path

plugin_bp = Blueprint("my_plugin", __name__)


@plugin_bp.route("/api/my-plugin/status")
def plugin_status():
    return jsonify({"status": "healthy", "nodes": 42})


@plugin_bp.route("/static/my-plugin/<path:filename>")
def serve_mfe_bundle(filename):
    static_dir = Path(__file__).parent / "dist"
    return send_from_directory(static_dir, filename)


class MyFleetExtensionPlugin(BaseEvalPlugin):
    def on_register_console_routes(self, app, nav_registry):
        # 1. Register backend API blueprint
        app.register_blueprint(plugin_bp)

        # 2. Inject navigation item into sidebar
        nav_registry.append(
            {
                "id": "fleet_management",
                "name": "Fleet APM",
                "path": "/fleet",
                "icon": "Cpu",
                "group": "Analyze",
                "badge": "LIVE",
                "tier": "enterprise",
                "remoteEntry": "/static/my-plugin/fleet-bundle.js",
                "required_role": ["System Admin", "MultiAgentOps Eng."],
            }
        )
```

---

### Step 2: Build the Micro-Frontend React Component

Create a standalone Vite/Rollup project for your custom tab.

#### Component Code (`src/FleetView.tsx`):
```tsx
import React, { useState, useEffect } from 'react';

export default function FleetView() {
  const [data, setData] = useState<{ status: string; nodes: number } | null>(null);

  useEffect(() => {
    fetch('/api/my-plugin/status')
      .then(res => res.json())
      .then(setData)
      .catch(console.error);
  }, []);

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">Agent Fleet Telemetry</h1>
          <p className="text-xs text-slate-400">Real-time distributed agent cluster telemetry.</p>
        </div>
        <span className="px-2.5 py-1 text-xs font-bold rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
          ● {data?.status || 'Connecting...'}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-5 rounded-xl bg-slate-900/60 border border-slate-800 space-y-1">
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Active Nodes</span>
          <p className="text-2xl font-mono font-bold text-indigo-400">{data?.nodes ?? '-'}</p>
        </div>
      </div>
    </div>
  );
}
```

#### Vite Configuration (`vite.config.ts`):
Configure Vite to bundle as a standalone standard ESM module:
```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: './src/FleetView.tsx',
      formats: ['es'],
      fileName: () => 'fleet-bundle.js',
    },
    rollupOptions: {
      // Externalize react/react-dom to share single runtime instance
      external: ['react', 'react-dom'],
      output: {
        globals: {
          react: 'React',
          'react-dom': 'ReactDOM',
        },
      },
    },
  },
});
```

---

## 🔒 Security & Fault Isolation

1. **Error Boundary Containment**: Remote components are automatically wrapped inside `RemoteErrorBoundary`. If a plugin throws a rendering or network error, only that tab displays a diagnostic card—the host console and sidebar remain completely operational.
2. **Standard Browser Security**: Remote ESM bundles imported via standard `import()` adhere to strict browser CORS policies and CSP headers.
3. **Graceful Offline Fallback**: If `/api/nav` is unreachable or the backend is offline, the Visual Console falls back cleanly to the built-in core navigation structure.
