import React from 'react';
import { ShellPage } from '../components/ShellPage';

export const SpecToEvalImporter: React.FC = () => (
  <ShellPage 
    title="Spec-to-Eval Importer" 
    description="Automatically convert raw Markdown PRDs or plain text feature requirements into executable AES benchmark scenarios using local and remote schema validators."
    endpoint="POST /api/v1/spec-to-eval"
    details="Module underlay: eval_runner/console/routes/scenarios.py (POST /v1/spec-to-eval)\nValidates structure against standard schemas/ definitions."
  />
);

export const AdversarialMutator: React.FC = () => (
  <ShellPage 
    title="Adversarial Scenario Mutator" 
    description="Generate fuzzing mutations, typos, ambiguous logic, or prompt injection variants of an existing AES scenario to evaluate safety floor tolerances."
    endpoint="POST /api/v1/mutate"
    details="Module underlay: eval_runner/console/routes/scenarios.py (POST /v1/mutate)\nTriggers backend mutator.py engines to append mutated variants."
  />
);

export const TraceExplain: React.FC = () => (
  <ShellPage 
    title="AI Trace Diagnostics (Explain)" 
    description="Deconstruct complex agent trace run graphs to locate execution loops, latency hotspots, policy violations, or sensitive data leaks using AI Judge logic."
    endpoint="GET /api/v1/explain/<run_id>"
    details="Module underlay: eval_runner/console/routes/runs.py (GET /v1/explain/<run_id>)\nUses judge-based text analysis of execution trace files."
  />
);

export const HITLQueue: React.FC = () => (
  <ShellPage 
    title="Human-in-the-Loop Queue" 
    description="View, approve, override, or supply missing data inputs for evaluations currently suspended in a pending-review state."
    endpoint="GET/POST /api/v1/hitl/queue"
    details="Module underlay: hitl/registry.py (requires thin REST wrapper blueprint).\nMonitors execution halts requesting external validation."
  />
);

export const Benchmarks: React.FC = () => (
  <ShellPage 
    title="Industry Benchmarks (GAIA / AssistantBench)" 
    description="Load, run, and compare standard third-party agent benchmarks, including GAIA, AssistantBench, and custom industry specific suites."
    endpoint="GET/POST /api/v1/benchmarks"
    details="Module underlay: benchmarks/ (gaia.py, assistantbench.py).\nCoordinates execution of third-party evaluation sets."
  />
);

