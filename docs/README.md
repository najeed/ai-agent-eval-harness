# AgentV Documentation Platform

This directory houses the authoritative documentation for **AgentV** (AI Agent Evaluation Harness), powered by [Astro](https://astro.build) and [Starlight](https://starlight.astro.build).

---

## 🏗️ Structure

```text
docs/
├── check_doc_paths.py     # CI Sentinel verifying all markdown path references exist on disk
├── astro.config.mjs       # Starlight sidebar navigation, search, and social configuration
├── package.json           # Documentation dependencies and build scripts
└── src/
    ├── assets/            # Static diagrams, badges, and brand assets
    └── content/
        └── docs/          # Structured documentation topics:
            ├── index.mdx              # Hero landing page
            ├── spec/                  # Formal specifications (AES, Trust Protocol, Packages, Mutation)
            ├── evaluator/             # Evaluator guides, CLI references, and Visual Suite
            ├── builder/               # Architecture, Frameworks, Providers, Developer Guide
            ├── extender/              # Plugins, Sandboxes, Simulators, Testing Guide
            ├── auditor/               # Security, Cryptographic Verification, Trust Protocol
            ├── integrator/            # Quickstarts and framework integration guides
            └── scholar/               # Determinism, Benchmarks, Luna-Judge, GAIA/SWE-Bench
```

---

## 💻 Development & Build Commands

All commands should be executed from within the `docs/` directory:

```bash
cd docs

# Install documentation dependencies
npm install

# Start local documentation dev server (http://localhost:4321)
npm run dev

# Build production static bundle to ./dist/
npm run build

# Preview production build locally
npm run preview
```

---

## 🛡️ Path Integrity Sentinel

Before committing documentation updates, run the path integrity sentinel from the project root to ensure all markdown file references and code links resolve:

```bash
python docs/check_doc_paths.py
```
