import React, { useState, useEffect, useMemo } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation, Outlet } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { CommandPalette } from './components/CommandPalette';
import {
  Home, FileText, Play, Activity, BarChart2, ShieldCheck,
  Settings, BookOpen, ChevronDown, ChevronRight, Menu, HeartPulse,
  AlertTriangle, CheckCircle2, Server, Bell, Layers, Cpu, Radio,
  Terminal, Zap, ExternalLink, Shield, Compass, Sparkles
} from 'lucide-react';
import { RBACProvider, useRBAC } from './context/RBACContext';
import type { UserRole } from './context/RBACContext';

// Import P1 Pages
import { Settings as SettingsPage } from './pages/Settings';
import { Docs as DocsPage } from './pages/Docs';
import { TrustCenter as TrustCenterPage } from './pages/TrustCenter';
import { Dashboard as DashboardPage } from './pages/Dashboard';
import { ScenarioLibrary as ScenarioLibraryPage } from './pages/ScenarioLibrary';
import { ScenarioComposer as ScenarioComposerPage } from './pages/ScenarioComposer';
import { EvaluationRunner as EvaluationRunnerPage } from './pages/EvaluationRunner';
import { LiveDebugger as LiveDebuggerPage } from './pages/LiveDebugger';
import { RunsReports as RunsReportsPage } from './pages/RunsReports';

// Import P2 Real Pages
import { MetricsLeaderboard } from './pages/MetricsLeaderboard';
import { FailureCorpus } from './pages/FailureCorpus';
import { Triage } from './pages/Triage';
import { ComplianceForensics } from './pages/ComplianceForensics';
import { PublicationSuite } from './pages/PublicationSuite';
import { CICDIntegration } from './pages/CICDIntegration';
import { RegistrySync } from './pages/RegistrySync';
import { HITLQueue } from './pages/HITLQueue';
import { AutoTranslate } from './pages/AutoTranslate';
import { Calibration } from './pages/Calibration';
import { Benchmarks } from './pages/Benchmarks';
import { SpecToEvalImporter } from './pages/SpecToEvalImporter';
import { AdversarialMutator } from './pages/AdversarialMutator';
import { TraceExplain } from './pages/TraceExplain';
import { RegressionSuites } from './pages/RegressionSuites';
import { CompliancePackEditor } from './pages/CompliancePackEditor';
import { verifySubresourceIntegrity } from './utils/crypto';

const queryClient = new QueryClient({

  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// Extended Nav Item schema
export interface NavItem {
  id?: string;
  name: string;
  path: string;
  icon?: string | React.ReactNode;
  group?: string;               // Target nav group (e.g., "Operations", "Audit & Compliance", "Build", "System")
  badge?: string;               // Optional badge chip (e.g., "LIVE", "HOT-RELOAD", "FLEET", "APM", "◆ ENT")
  tier?: 'core' | 'enterprise'; // Visual delineation marker
  remoteEntry?: string;         // ESM bundle URL for dynamic micro-frontend mounting
  required_role?: string[];     // Optional RBAC role gating
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

/**
 * Dynamic Icon Resolver: Maps string icon identifiers to Lucide icon elements
 */
const resolveIcon = (icon: string | React.ReactNode | undefined): React.ReactNode => {
  if (React.isValidElement(icon)) return icon;
  if (typeof icon === 'string') {
    const key = icon.toLowerCase().replace(/[-_]/g, '');
    switch (key) {
      case 'home':
        return <Home className="w-4 h-4" />;
      case 'filetext':
        return <FileText className="w-4 h-4" />;
      case 'play':
        return <Play className="w-4 h-4" />;
      case 'activity':
        return <Activity className="w-4 h-4" />;
      case 'barchart':
      case 'barchart2':
        return <BarChart2 className="w-4 h-4" />;
      case 'shieldcheck':
        return <ShieldCheck className="w-4 h-4" />;
      case 'shield':
        return <Shield className="w-4 h-4" />;
      case 'settings':
        return <Settings className="w-4 h-4" />;
      case 'bookopen':
      case 'docs':
        return <BookOpen className="w-4 h-4" />;
      case 'server':
        return <Server className="w-4 h-4" />;
      case 'bell':
        return <Bell className="w-4 h-4" />;
      case 'heartpulse':
        return <HeartPulse className="w-4 h-4" />;
      case 'layers':
        return <Layers className="w-4 h-4" />;
      case 'cpu':
        return <Cpu className="w-4 h-4" />;
      case 'radio':
        return <Radio className="w-4 h-4" />;
      case 'terminal':
        return <Terminal className="w-4 h-4" />;
      case 'zap':
        return <Zap className="w-4 h-4" />;
      case 'compass':
        return <Compass className="w-4 h-4" />;
      case 'sparkles':
        return <Sparkles className="w-4 h-4" />;
      default:
        return <ChevronRight className="w-3.5 h-3.5" />;
    }
  }
  return <ChevronRight className="w-3.5 h-3.5" />;
};

/**
 * Merges backend GET /api/nav items with hardcoded fallback base navigation groups.
 */
export function mergeNavManifest(
  baseGroups: NavGroup[],
  remoteItems: any[] | null | undefined
): NavGroup[] {
  if (!remoteItems || !Array.isArray(remoteItems) || remoteItems.length === 0) {
    return baseGroups;
  }

  // Deep clone base groups
  const merged: NavGroup[] = baseGroups.map(g => ({
    title: g.title,
    items: [...g.items],
  }));

  const existingPaths = new Set<string>();
  merged.forEach(g => g.items.forEach(item => existingPaths.add(item.path)));

  for (const rawItem of remoteItems) {
    if (!rawItem || typeof rawItem !== 'object') continue;
    const name = rawItem.name || rawItem.id || 'Plugin Item';
    const path = rawItem.path || (rawItem.id ? `/${rawItem.id}` : '#');
    if (existingPaths.has(path)) continue;

    const targetGroupTitle =
      rawItem.group || (rawItem.tier === 'enterprise' ? 'Enterprise' : 'System');

    const navItem: NavItem = {
      id: rawItem.id,
      name,
      path,
      icon: resolveIcon(rawItem.icon),
      badge: rawItem.badge,
      tier: rawItem.tier,
      remoteEntry: rawItem.remoteEntry,
      required_role: Array.isArray(rawItem.required_role)
        ? rawItem.required_role
        : undefined,
    };

    let targetGroup = merged.find(
      g => g.title.toLowerCase() === targetGroupTitle.toLowerCase()
    );
    if (!targetGroup) {
      targetGroup = { title: targetGroupTitle, items: [] };
      const systemIdx = merged.findIndex(g => g.title.toLowerCase() === 'system');
      if (systemIdx !== -1) {
        merged.splice(systemIdx, 0, targetGroup);
      } else {
        merged.push(targetGroup);
      }
    }
    targetGroup.items.push(navItem);
    existingPaths.add(path);
  }

  return merged;
}

interface RemoteErrorState {
  hasError: boolean;
  error?: Error;
}

class RemoteErrorBoundary extends React.Component<
  { children: React.ReactNode; entryUrl: string },
  RemoteErrorState
> {
  constructor(props: { children: React.ReactNode; entryUrl: string }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): RemoteErrorState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error(`[MicroFrontend] Failed to load remote entry: ${this.props.entryUrl}`, error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full min-h-[400px] flex-col items-center justify-center p-8 text-center">
          <div className="p-6 bg-red-500/10 border border-red-500/20 rounded-2xl max-w-lg shadow-xl backdrop-blur">
            <AlertTriangle className="w-10 h-10 mx-auto mb-3 text-red-400" />
            <h3 className="font-bold text-base text-red-300">Failed to Load Micro-Frontend Module</h3>
            <p className="text-xs text-slate-400 mt-2 font-mono break-all bg-slate-950/60 p-2.5 rounded-lg border border-slate-900">
              {this.props.entryUrl}
            </p>
            <p className="text-[11px] text-red-400/80 mt-2">{this.state.error?.message || 'Module fetch or evaluation failed.'}</p>
          </div>
        </div>
      );
      return this.props.children;
    }
  }
}

/**
 * Generic Runtime Micro-Frontend Remote Loader:
 * Loads dynamic ESM components on demand behind a signed origin and cryptographic SRI verification policy.
 * Natively enforces FIPS 202 SHA3-256 / SHA3-384 / SHA3-512 with legacy WebCrypto SHA-2 fallback.
 */

export const RemoteComponentLoader: React.FC<{ entryUrl: string; sriHash?: string }> = ({ entryUrl, sriHash }) => {
  const [loadingState, setLoadingState] = useState<{
    status: 'idle' | 'verifying' | 'ready' | 'untrusted_origin' | 'sri_failed' | 'load_error';
    Component?: React.ComponentType<any>;
    errorMessage?: string;
    computedDigest?: string;
  }>({ status: 'idle' });

  const isTrustedOrigin = useMemo(() => {
    try {
      if (entryUrl.startsWith('/') || entryUrl.startsWith('./')) return true;
      const parsed = new URL(entryUrl, window.location.origin);
      return (
        parsed.hostname === window.location.hostname ||
        parsed.hostname === 'localhost' ||
        parsed.hostname === '127.0.0.1'
      );
    } catch {
      return false;
    }
  }, [entryUrl]);

  useEffect(() => {
    let active = true;
    let blobUrlToRevoke: string | null = null;

    async function loadAndVerifyModule() {
      if (!isTrustedOrigin) {
        if (active) setLoadingState({ status: 'untrusted_origin' });
        return;
      }

      try {
        if (active) setLoadingState({ status: 'verifying' });

        // If SRI hash is provided, enforce byte-level integrity verification
        if (sriHash) {
          const res = await fetch(entryUrl);
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}: Failed to fetch remote module.`);
          }
          const buffer = await res.arrayBuffer();

          const { valid, computed, algorithm } = await verifySubresourceIntegrity(buffer, sriHash);

          if (!valid) {
            console.error(`[ZeroTrust SRI] ${algorithm} digest mismatch for ${entryUrl}. Expected: ${sriHash}, Computed: ${computed}`);
            if (active) {
              setLoadingState({
                status: 'sri_failed',
                errorMessage: `Integrity check failed (${algorithm}): expected ${sriHash}, got ${computed}`,
                computedDigest: computed,
              });
            }
            return;
          }

          // Integrity validated: instantiate via ephemeral Blob URL
          const blob = new Blob([buffer], { type: 'text/javascript' });
          blobUrlToRevoke = URL.createObjectURL(blob);
          const mod = await import(/* @vite-ignore */ blobUrlToRevoke);
          const ResolvedComp = mod.default || mod[Object.keys(mod)[0]] || mod;
          if (active) setLoadingState({ status: 'ready', Component: ResolvedComp });
        } else {
          // Direct dynamic ESM import for local/trusted origin without SRI pin
          const mod = await import(/* @vite-ignore */ entryUrl);
          const ResolvedComp = mod.default || mod[Object.keys(mod)[0]] || mod;
          if (active) setLoadingState({ status: 'ready', Component: ResolvedComp });
        }
      } catch (err: any) {
        console.error(`[ZeroTrust Loader] Error mounting module ${entryUrl}:`, err);
        if (active) {
          setLoadingState({
            status: 'load_error',
            errorMessage: err?.message || 'Module evaluation failed.',
          });
        }
      }
    }

    loadAndVerifyModule();

    return () => {
      active = false;
      if (blobUrlToRevoke) {
        URL.revokeObjectURL(blobUrlToRevoke);
      }
    };
  }, [entryUrl, sriHash, isTrustedOrigin]);

  if (loadingState.status === 'untrusted_origin') {
    return (
      <div className="flex h-full min-h-[400px] flex-col items-center justify-center p-8 text-center">
        <div className="p-6 bg-red-500/10 border border-red-500/20 rounded-2xl max-w-lg shadow-xl backdrop-blur">
          <AlertTriangle className="w-10 h-10 mx-auto mb-3 text-red-400" />
          <h3 className="font-bold text-base text-red-300">Untrusted Extension Origin Blocked</h3>
          <p className="text-xs text-slate-400 mt-2 font-mono break-all bg-slate-950/60 p-2.5 rounded-lg border border-slate-900">
            {entryUrl}
          </p>
          <p className="text-[11px] text-red-400/80 mt-2">
            Module origin is outside the trusted domain policy and was blocked by Zero-Trust security rules.
          </p>
        </div>
      </div>
    );
  }

  if (loadingState.status === 'sri_failed') {
    return (
      <div className="flex h-full min-h-[400px] flex-col items-center justify-center p-8 text-center">
        <div className="p-6 bg-red-500/10 border border-red-500/30 rounded-2xl max-w-lg shadow-xl backdrop-blur">
          <AlertTriangle className="w-10 h-10 mx-auto mb-3 text-red-400" />
          <h3 className="font-bold text-base text-red-300">Subresource Integrity (SRI) Violation</h3>
          <p className="text-xs text-slate-400 mt-2 font-mono break-all bg-slate-950/60 p-2.5 rounded-lg border border-slate-900">
            {entryUrl}
          </p>
          <div className="mt-3 text-left space-y-1 bg-slate-950/80 p-3 rounded-lg border border-red-500/20 font-mono text-[10px]">
            <div className="text-red-400">Expected: {sriHash}</div>
            <div className="text-amber-400">Actual: {loadingState.computedDigest}</div>
          </div>
          <p className="text-[11px] text-red-400/80 mt-3">
            Cryptographic integrity mismatch detected. Execution blocked to prevent tamper attacks.
          </p>
        </div>
      </div>
    );
  }

  if (loadingState.status === 'load_error') {
    return (
      <div className="flex h-full min-h-[400px] flex-col items-center justify-center p-8 text-center">
        <div className="p-6 bg-red-500/10 border border-red-500/20 rounded-2xl max-w-lg shadow-xl backdrop-blur">
          <AlertTriangle className="w-10 h-10 mx-auto mb-3 text-red-400" />
          <h3 className="font-bold text-base text-red-300">Failed to Load Extension Module</h3>
          <p className="text-xs text-slate-400 mt-2 font-mono break-all bg-slate-950/60 p-2.5 rounded-lg border border-slate-900">
            {entryUrl}
          </p>
          <p className="text-[11px] text-red-400/80 mt-2">{loadingState.errorMessage}</p>
        </div>
      </div>
    );
  }

  if (loadingState.status === 'ready' && loadingState.Component) {
    const Component = loadingState.Component;
    return (
      <RemoteErrorBoundary entryUrl={entryUrl}>
        <Component />
      </RemoteErrorBoundary>
    );
  }

  return (
    <div className="flex h-full min-h-[400px] items-center justify-center p-8">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-xs font-mono text-slate-400">
          {sriHash ? 'Verifying cryptographic subresource integrity...' : 'Loading module...'}
        </span>
      </div>
    </div>
  );
};


const JobTray: React.FC = () => {
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('');
  const [progress, setProgress] = useState<string>('');
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    const checkJob = () => {
      const activeId = localStorage.getItem('agentv-active-pub-job');
      setJobId(activeId);
    };

    checkJob();
    const interval = setInterval(checkJob, 2000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!jobId) {
      setStatus('');
      setProgress('');
      return;
    }

    let intervalId: any = null;

    const fetchStatus = async () => {
      try {
        const activeIdInStorage = localStorage.getItem('agentv-active-pub-job');
        if (!activeIdInStorage || activeIdInStorage !== jobId) {
          if (intervalId) clearInterval(intervalId);
          return;
        }

        const res = await fetch(`/api/publish/${jobId}`);
        if (res.status === 404) {
          localStorage.removeItem('agentv-active-pub-job');
          if (intervalId) clearInterval(intervalId);
          setStatus('failed');
          return;
        }
        if (res.ok) {
          const data = await res.json();
          if (localStorage.getItem('agentv-active-pub-job') === jobId) {
            setStatus(data.status);
            setProgress(data.progress);
            if (data.status === 'completed' || data.status === 'failed') {
              if (intervalId) clearInterval(intervalId);
            }
          }
        }
      } catch (e) {
        console.error('Job polling error', e);
      }
    };

    fetchStatus();
    intervalId = setInterval(fetchStatus, 1500);

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [jobId]);

  if (!jobId) return null;

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-2.5 py-1 bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-lg text-xs transition-all text-slate-300 font-sans shadow-sm"
      >
        <span className="relative flex h-2 w-2">
          {status === 'running' && (
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          )}
          <span className={`relative inline-flex rounded-full h-2 w-2 ${status === 'completed' ? 'bg-emerald-500' :
            status === 'failed' ? 'bg-red-500' :
              'bg-amber-500'
            }`}></span>
        </span>
        <span className="font-semibold text-[11px]">
          {status === 'completed' ? 'Publication Ready' :
            status === 'failed' ? 'Job Failed' :
              'Publishing Pack...'}
        </span>
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-64 p-3 bg-slate-900/95 border border-slate-800 rounded-xl shadow-2xl backdrop-blur z-50 space-y-2.5 animate-in fade-in zoom-in-95 duration-100 font-sans">
          <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
            <span className="text-xs font-bold text-slate-200">Active Task</span>
            <span className={`text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded border ${status === 'completed' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
              status === 'failed' ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                'bg-amber-500/10 text-amber-400 border-amber-500/20'
              }`}>
              {status || 'running'}
            </span>
          </div>

          <div className="space-y-1">
            <span className="text-[9px] text-slate-500 font-bold uppercase font-mono">Job ID: {jobId.slice(0, 15)}...</span>
            <p className="text-[10px] text-slate-300 italic leading-snug">{progress || 'Pending...'}</p>
          </div>

          <Link
            to="/publish"
            onClick={() => setIsOpen(false)}
            className="block text-center py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-[10px] font-bold transition-colors"
          >
            Open Job Console
          </Link>
        </div>
      )}
    </div>
  );
};

const ConsoleLayout: React.FC = () => {
  const location = useLocation();
  const { user, role, setRole, isDevMode, canAccessSettings, canEditScenario, canRunEval, canSignCert } = useRBAC();
  const [isCmdOpen, setIsCmdOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [toasts, setToasts] = useState<{ id: string; message: string; type: string }[]>([]);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    Overview: true,
    Work: true,
    Govern: true,
    Admin: true,
  });

  // Dynamic Manifest Query (TanStack Query)
  const { data: remoteNav } = useQuery({
    queryKey: ['console-nav-registry'],
    queryFn: async () => {
      const res = await fetch('/api/nav');
      if (!res.ok) return null;
      const data = await res.json();
      return Array.isArray(data) ? data : (data.nav || []);
    },
    staleTime: 60_000,
  });

  useEffect(() => {
    // Intercept window fetch for global authentication diagnostics
    const originalFetch = window.fetch;
    window.fetch = async (...args) => {
      try {
        const response = await originalFetch(...args);
        if (response.status === 401 || response.status === 403) {
          window.dispatchEvent(new CustomEvent('agentv-toast', {
            detail: { message: 'Authentication Failure: Invalid API credentials.', type: 'error' }
          }));
        }
        return response;
      } catch (err: any) {
        window.dispatchEvent(new CustomEvent('agentv-toast', {
          detail: { message: `Harness Connection Error: ${err.message}`, type: 'warning' }
        }));
        throw err;
      }
    };

    const handleToast = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      const id = Math.random().toString(36).substr(2, 9);
      setToasts(prev => [...prev, { id, ...detail }]);
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id));
      }, 4000);
    };

    window.addEventListener('agentv-toast', handleToast);
    return () => {
      window.fetch = originalFetch;
      window.removeEventListener('agentv-toast', handleToast);
    };
  }, []);

  const toggleGroup = (title: string) => {
    setExpandedGroups(prev => ({ ...prev, [title]: !prev[title] }));
  };

  const baseNavGroups: NavGroup[] = [
    {
      title: 'Workflow',
      items: [
        { name: 'New Verification', path: '/', icon: <Home className="w-4 h-4" /> },
      ],
    },
    {
      title: 'Scenarios',
      items: [
        { name: 'Scenario Library', path: '/scenarios', icon: <FileText className="w-4 h-4" /> },
        { name: 'Visual Composer', path: '/editor', icon: <Activity className="w-4 h-4" /> },
        { name: 'Suites & Benchmarks', path: '/suites', icon: <Layers className="w-4 h-4" /> },
      ],
    },
    {
      title: 'Runs',
      items: [
        { name: 'Active & History', path: '/reports', icon: <BarChart2 className="w-4 h-4" /> },
        { name: 'Live Debugger', path: '/debugger', icon: <Play className="w-4 h-4" /> },
        { name: 'Evaluation Runner', path: '/runner', icon: <Cpu className="w-4 h-4" /> },
        { name: 'Triage Center', path: '/triage', icon: <AlertTriangle className="w-4 h-4" /> },
      ],
    },
    {
      title: 'Evidence',
      items: [
        { name: 'Verification & Packages', path: '/reports', icon: <FileText className="w-4 h-4" /> },
        { name: 'Trust Center', path: '/trust', icon: <ShieldCheck className="w-4 h-4" /> },
        { name: 'Compliance Forensics', path: '/compliance', icon: <Shield className="w-4 h-4" /> },
        { name: 'Publication Suite', path: '/publish', icon: <Zap className="w-4 h-4" /> },
      ],
    },
    {
      title: 'Advanced',
      items: [
        { name: 'Adversarial Mutator', path: '/mutator', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Spec-to-Eval Importer', path: '/spec-import', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Auto-Translate', path: '/translate', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Calibration Console', path: '/calibration', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'HITL Queue', path: '/hitl', icon: <Activity className="w-4 h-4" /> },
        { name: 'Trace Explain (AI)', path: '/explain', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Failure Corpus', path: '/failures', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Metrics Leaderboard', path: '/metrics', icon: <BarChart2 className="w-4 h-4" /> },
        { name: 'CI/CD Pipelines', path: '/cicd', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Documentation', path: '/docs', icon: <BookOpen className="w-4 h-4" /> },
        { name: 'Settings & Security', path: '/settings', icon: <Settings className="w-4 h-4" /> },
      ],
    },
  ];

  // Merge dynamic plugin groups with core built-in navigation
  const navGroups = useMemo(() => {
    return mergeNavManifest(baseNavGroups, remoteNav);
  }, [remoteNav]);

  // Role-based nav access gating
  const isNavItemRestricted = (item: NavItem): boolean => {
    if (item.required_role && item.required_role.length > 0) {
      if (!item.required_role.includes(role)) return true;
    }
    if (item.path === '/settings' && !canAccessSettings) return true;
    if (item.path === '/editor' && !canEditScenario) return true;
    if (item.path === '/runner' && !canRunEval) return true;
    if (item.path === '/trust' && !canSignCert) return true;
    return false;
  };

  const roleColors: Record<string, string> = {
    'System Admin': 'text-indigo-400 bg-indigo-500/10 border-indigo-500/20',
    'Compliance Auditor': 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20',
    'Scenario Designer': 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
    'MultiAgentOps Eng.': 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-navy-base font-sans antialiased text-slate-200">
      <CommandPalette isOpen={isCmdOpen} setIsOpen={setIsCmdOpen} />

      {/* Sidebar Navigation */}
      <aside
        className={`bg-slate-950/40 border-r border-slate-900 flex flex-col shrink-0 transition-all duration-300 ${sidebarCollapsed ? 'w-16' : 'w-64'
          }`}
      >
        {/* Header / Brand */}
        <div className="h-14 border-b border-slate-900 flex items-center justify-between px-3">
          {sidebarCollapsed ? (
            <img
              src="/favicon.png"
              alt="AgentV"
              className="w-8 h-8 rounded-lg object-contain"
            />
          ) : (
            <div className="flex items-center gap-2 min-w-0">
              <img
                src="/logo-premium.png"
                alt="AgentV Console"
                className="h-8 w-auto object-contain rounded"
              />
              <div className="flex flex-col min-w-0">
                <span className="font-bold text-xs tracking-wide text-white uppercase leading-tight">AgentV Console</span>
                <span className="text-[9px] text-slate-500 font-medium leading-tight"></span>
              </div>
            </div>
          )}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="p-1.5 rounded-lg hover:bg-slate-900 text-slate-400 hover:text-white transition-colors shrink-0"
          >
            <Menu className="w-4 h-4" />
          </button>
        </div>

        {/* Navigation Groups */}
        <div className="flex-1 overflow-y-auto p-3 space-y-4">
          {navGroups.map(group => {
            const isExpanded = expandedGroups[group.title] ?? true;
            return (
              <div key={group.title} className="space-y-1">
                {/* Group Heading */}
                {!sidebarCollapsed && (
                  <button
                    onClick={() => toggleGroup(group.title)}
                    className="flex items-center justify-between w-full px-2.5 py-1 text-left text-[10px] font-bold text-slate-500 uppercase tracking-wider hover:text-slate-400"
                  >
                    <span>{group.title}</span>
                    {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                  </button>
                )}

                {/* Group Items */}
                {(isExpanded || sidebarCollapsed) && (
                  <div className="space-y-0.5">
                    {group.items.map(item => {
                      const isActive = location.pathname === item.path || (item.path !== '/' && !item.path.startsWith('http') && location.pathname.startsWith(item.path));
                      const restricted = isNavItemRestricted(item);
                      const isExternal = item.path.startsWith('http://') || item.path.startsWith('https://');

                      if (restricted) {
                        return (
                          <div
                            key={item.id || item.name}
                            title="Restricted: insufficient role permissions"
                            className="flex items-center gap-3 px-3 py-2 rounded-lg text-xs border border-transparent text-slate-600 opacity-50 cursor-not-allowed select-none"
                          >
                            <div className="shrink-0">{item.icon}</div>
                            {!sidebarCollapsed && <span className="truncate">{item.name}</span>}
                            {!sidebarCollapsed && <span className="ml-auto text-[8px] uppercase tracking-wider text-slate-600 font-bold">🔒</span>}
                          </div>
                        );
                      }

                      if (isExternal) {
                        return (
                          <a
                            key={item.id || item.path || item.name}
                            href={item.path}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-3 px-3 py-2 rounded-lg text-xs border border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/50 transition-all"
                          >
                            <div className="shrink-0">{item.icon}</div>
                            {!sidebarCollapsed && <span className="truncate">{item.name}</span>}
                            {item.badge && !sidebarCollapsed && (
                              <span className={`ml-auto text-[9px] font-mono font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border shrink-0 ${item.tier === 'enterprise'
                                ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                                : 'bg-indigo-500/10 text-indigo-300 border-indigo-500/30'
                                }`}>
                                {item.badge}
                              </span>
                            )}
                            {!item.badge && !sidebarCollapsed && <ExternalLink className="ml-auto w-3 h-3 text-slate-500" />}
                          </a>
                        );
                      }

                      return (
                        <Link
                          key={item.id || item.name}
                          to={item.path}
                          className={`flex items-center gap-3 px-3 py-2 rounded-lg text-xs transition-all ${isActive
                            ? 'bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 font-bold'
                            : 'border border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/50'
                            }`}
                        >
                          <div className="shrink-0">{item.icon}</div>
                          {!sidebarCollapsed && <span className="truncate">{item.name}</span>}
                          {item.badge && !sidebarCollapsed && (
                            <span className={`ml-auto text-[9px] font-mono font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border shrink-0 ${item.tier === 'enterprise'
                              ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                              : 'bg-indigo-500/10 text-indigo-300 border-indigo-500/30'
                              }`}>
                              {item.badge}
                            </span>
                          )}
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer info */}
        {!sidebarCollapsed && (
          <div className="p-4 border-t border-slate-900/50 space-y-2">
            <div className={`px-2 py-1.5 rounded-lg border text-[10px] font-bold uppercase tracking-wider text-center ${roleColors[role] || 'text-slate-400'}`}>
              {role}
            </div>
            <div className="flex items-center justify-between text-[10px] text-slate-500">
              <span className="font-medium">Press ⌘K for actions</span>
              <span className="flex items-center gap-1">
                <HeartPulse className="w-3.5 h-3.5 text-emerald-500" /> API Alive
              </span>
            </div>
          </div>
        )}
      </aside>

      {/* Main Panel Viewport */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Header / Breadcrumbs */}
        <header className="h-14 border-b border-slate-900 flex items-center justify-between px-6 bg-slate-950/10 shrink-0">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span className="font-semibold text-slate-300">AgentV Suite</span>
            <span>/</span>
            <span className="text-slate-500 capitalize">{location.pathname.replace('/', '') || 'Dashboard'}</span>
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={() => setIsCmdOpen(true)}
              className="flex items-center gap-2 px-3 py-1.5 bg-slate-950 border border-slate-850 rounded-lg text-slate-500 hover:text-slate-400 text-xs transition-colors"
            >
              <span>Search command...</span>
              <kbd className="bg-slate-900 px-1.5 py-0.5 rounded text-[9px] font-mono border border-slate-800 text-slate-400">⌘K</kbd>
            </button>

            <JobTray />

            {/* Persona Switcher Dropdown (Developer Simulator only) */}
            {isDevMode ? (
              <div className="flex items-center gap-1.5 border-l border-slate-900 pl-3">
                <span className="text-[9px] text-amber-400 font-bold uppercase tracking-wider font-mono">[Dev Persona]:</span>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value as UserRole)}
                  className="bg-slate-950 border border-amber-500/30 text-amber-300 font-bold rounded px-2.5 py-1 text-[11px] focus:outline-none focus:border-amber-500 font-sans cursor-pointer"
                >
                  <option value="System Admin">System Admin</option>
                  <option value="Compliance Auditor">Compliance Auditor</option>
                  <option value="Scenario Designer">Scenario Designer</option>
                  <option value="MultiAgentOps Eng.">MultiAgentOps Eng.</option>
                </select>
              </div>
            ) : (
              <div className="flex items-center gap-2 border-l border-slate-900 pl-3">
                <span className="text-xs text-slate-300 font-medium">{user?.name || 'Operator'}</span>
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${roleColors[role] || 'text-slate-400'}`}>
                  {role}
                </span>
              </div>
            )}
          </div>
        </header>


        {/* Page Content Viewport */}
        <main className="flex-1 overflow-y-auto bg-navy-base">
          <Outlet />
        </main>
      </div>

      {/* Global Toast Container */}
      <div className="fixed top-4 right-4 z-50 space-y-2 pointer-events-none">
        {toasts.map(t => (
          <div
            key={t.id}
            className={`p-4 rounded-xl border shadow-2xl backdrop-blur bg-slate-900/90 text-xs text-white max-w-sm pointer-events-auto flex items-start gap-3 transition-all transform duration-300 animate-slide-in ${t.type === 'error' ? 'border-red-500/20 text-red-300' :
              t.type === 'success' ? 'border-emerald-500/20 text-emerald-300' :
                t.type === 'warning' ? 'border-amber-500/20 text-amber-300' :
                  'border-indigo-500/20 text-indigo-300'
              }`}
          >
            {t.type === 'error' && <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />}
            {t.type === 'success' && <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />}
            {t.type === 'warning' && <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />}
            {t.type === 'info' && <Server className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />}
            <span className="leading-relaxed font-semibold">{t.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

function AppRoutes() {
  const { data: remoteNav } = useQuery({
    queryKey: ['console-nav-registry'],
    queryFn: async () => {
      const res = await fetch('/api/nav');
      if (!res.ok) return null;
      const data = await res.json();
      return Array.isArray(data) ? data : (data.nav || []);
    },
    staleTime: 60_000,
  });

  const remoteRoutes = useMemo(() => {
    if (!remoteNav || !Array.isArray(remoteNav)) return [];
    return remoteNav.filter(
      (item: any) =>
        item &&
        item.remoteEntry &&
        item.path &&
        !item.path.startsWith('http://') &&
        !item.path.startsWith('https://')
    );
  }, [remoteNav]);

  return (
    <Routes>
      <Route element={<ConsoleLayout />}>
        {/* P1 Main Screens */}
        <Route path="/" element={<DashboardPage />} />
        <Route path="/scenarios" element={<ScenarioLibraryPage />} />
        <Route path="/scenarios/compose" element={<ScenarioComposerPage />} />
        <Route path="/editor" element={<ScenarioComposerPage />} />
        <Route path="/runner" element={<EvaluationRunnerPage />} />
        <Route path="/debugger" element={<LiveDebuggerPage />} />
        <Route path="/reports" element={<RunsReportsPage />} />
        <Route path="/runs" element={<RunsReportsPage />} />
        <Route path="/evidence" element={<RunsReportsPage />} />
        <Route path="/evidence/packages" element={<RunsReportsPage />} />
        <Route path="/trust" element={<TrustCenterPage />} />
        <Route path="/docs" element={<DocsPage />} />
        <Route path="/settings" element={<SettingsPage />} />


        {/* P2 Shell Screens */}
        <Route path="/spec-import" element={<SpecToEvalImporter />} />
        <Route path="/mutator" element={<AdversarialMutator />} />
        <Route path="/explain" element={<TraceExplain />} />
        <Route path="/hitl" element={<HITLQueue />} />
        <Route path="/translate" element={<AutoTranslate />} />
        <Route path="/calibration" element={<Calibration />} />
        <Route path="/metrics" element={<MetricsLeaderboard />} />
        <Route path="/failures" element={<FailureCorpus />} />
        <Route path="/triage" element={<Triage />} />
        <Route path="/benchmarks" element={<Benchmarks />} />
        <Route path="/compliance" element={<ComplianceForensics />} />
        <Route path="/publish" element={<PublicationSuite />} />
        <Route path="/cicd" element={<CICDIntegration />} />
        <Route path="/sync" element={<RegistrySync />} />
        <Route path="/suites" element={<RegressionSuites />} />
        <Route path="/packs" element={<CompliancePackEditor />} />

        {/* Dynamic Micro-Frontend Remote Routes */}
        {remoteRoutes.map((item: any) => (
          <Route
            key={item.path}
            path={item.path.startsWith('/') ? item.path : `/${item.path}`}
            element={
              <RemoteComponentLoader
                entryUrl={item.remoteEntry}
                sriHash={item.sriHash || item.integrity || item.sri}
              />
            }
          />
        ))}

      </Route>
    </Routes>
  );
}

const getConsoleBasename = () => {
  if (typeof window !== 'undefined' && window.location.pathname.startsWith('/v2')) {
    return '/v2';
  }
  return '';
};

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RBACProvider>
        <BrowserRouter basename={getConsoleBasename()}>
          <AppRoutes />
        </BrowserRouter>
      </RBACProvider>
    </QueryClientProvider>
  );
}

export default App;

