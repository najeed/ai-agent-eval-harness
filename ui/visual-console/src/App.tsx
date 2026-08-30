import React, { useState, useEffect, useMemo } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation, Outlet, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { CommandPalette } from './components/CommandPalette';
import {
  Home, FileText, Play, Activity, BarChart2, ShieldCheck,
  Settings, BookOpen, ChevronDown, ChevronRight, Menu, HeartPulse,
  AlertTriangle, CheckCircle2, Server, Bell, Layers, Cpu, Radio,
  Terminal, Zap, ExternalLink, Shield, Compass, Sparkles
} from 'lucide-react';
import { RBACProvider, useRBAC } from './context/RBACContext';

// Import P1 Pages (Runtime OSS Core)
import { Settings as SettingsPage } from './pages/Settings';
import { Docs as DocsPage } from './pages/Docs';
import { TrustCenter as TrustCenterPage } from './pages/TrustCenter';
import { Dashboard as DashboardPage } from './pages/Dashboard';
import { VerificationWorkflow as VerificationWorkflowPage } from './pages/VerificationWorkflow';
import { ScenarioLibrary as ScenarioLibraryPage } from './pages/ScenarioLibrary';
import { ScenarioComposer as ScenarioComposerPage } from './pages/ScenarioComposer';
import { LiveDebugger as LiveDebuggerPage } from './pages/LiveDebugger';
import { RunsReports as RunsReportsPage } from './pages/RunsReports';

// Import Diagnostics & Tooling Pages (Runtime OSS Diagnostics)
import { FailureCorpus } from './pages/FailureCorpus';
import { Triage } from './pages/Triage';
import { SpecToEvalImporter } from './pages/SpecToEvalImporter';
import { AdversarialMutator } from './pages/AdversarialMutator';

// Extension host: generic load/contract fallback + RuntimeExtension contract
import { ExtensionLoadError } from './components/ExtensionLoadError';
import { RemoteErrorBoundary } from './components/RemoteErrorBoundary';
import {
  validateExtensionManifest,
  EXTENSION_CONTRACT_VERSION,
  hostApisForTier,
  canCallHostApi,
  READ_ONLY_HOST_APIS,
  type ExtensionTier,
  type RuntimeExtensionManifest,
} from './types/extension-contract';
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
  tier?: 'core' | 'enterprise' | 'local'; // Visual delineation marker
                                // [D2] 'local': unsigned plugin contribution — flagged in nav and limited to read-only host APIs.
  remoteEntry?: string;         // ESM bundle URL for dynamic micro-frontend mounting
  sriHash?: string;             // Subresource integrity digest (FIPS 202 SHA3 / WebCrypto SHA-2)
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
      sriHash: rawItem.sriHash || rawItem.integrity || rawItem.sri,
      required_role: Array.isArray(rawItem.required_role)
        ? rawItem.required_role
        : undefined,
      // [D2] Unsigned plugin contributions are stamped LOCAL: they render a
      // visible flag in the nav. Signed contributions must carry their own SRI.
      ...(rawItem.tier
        ? { tier: rawItem.tier }
        : !(rawItem.sriHash || rawItem.integrity || rawItem.sri)
          ? { tier: 'local' as const }
          : {}),
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

// ---------------------------------------------------------------------------
// [D2] Extension host API surface. Extensions receive ONLY the APIs their
// trust tier grants: unsigned/local extensions are restricted to read-only
// host APIs; there is deliberately no escape hatch client-side.
// ---------------------------------------------------------------------------

interface ExtensionHostApiInfo {
  tier: ExtensionTier;
  allowedApis: readonly string[];
  /** Tier-gated host-API authorization check (string-typed for forward compat). */
  can(call: string): boolean;
}

const ExtensionHostContext = React.createContext<ExtensionHostApiInfo>({
  tier: 'unsigned-local',
  allowedApis: READ_ONLY_HOST_APIS,
  can: () => false,
});

export const useExtensionHost = (): ExtensionHostApiInfo =>
  React.useContext(ExtensionHostContext);

const ExtensionHostProvider: React.FC<{
  tier: ExtensionTier;
  manifest?: RuntimeExtensionManifest;
  children: React.ReactNode;
}> = ({
  tier,
  manifest,
  children,
}) => {
  const value = useMemo<ExtensionHostApiInfo>(() => {
    const tierApis = hostApisForTier(tier);
    const allowedApis = manifest?.host_apis
      ? tierApis.filter(api => manifest.host_apis.includes(api))
      : tierApis;
    return {
      tier,
      allowedApis,
      can: (call: string) => canCallHostApi(tier, call, manifest),
    };
  }, [tier, manifest]);
  return <ExtensionHostContext.Provider value={value}>{children}</ExtensionHostContext.Provider>;
};


/**
 * Generic Runtime Micro-Frontend Remote Loader:
 * Loads dynamic ESM components on demand behind a signed origin and cryptographic SRI verification policy.
 * Natively enforces FIPS 202 SHA3-256 / SHA3-384 / SHA3-512 with legacy WebCrypto SHA-2 fallback.
 */

export const RemoteComponentLoader: React.FC<{ entryUrl: string; sriHash?: string }> = ({ entryUrl, sriHash }) => {
  const [loadingState, setLoadingState] = useState<{
    status:
      | 'idle'
      | 'verifying'
      | 'ready'
      | 'untrusted_origin'
      | 'sri_failed'
      | 'contract_violation'
      | 'publisher_failed'
      | 'load_error';
    Component?: React.ComponentType<any>;
    errorMessage?: string;
    computedDigest?: string;
    violations?: string[];
    publisherReason?: string;
    tier?: ExtensionTier;
    manifest?: RuntimeExtensionManifest;
  }>({ status: 'idle' });


  const isTrustedOrigin = useMemo(() => {
    try {
      if (entryUrl.startsWith('/') || entryUrl.startsWith('./')) return true;
      // Cross-origin extensions are allowed if pinned with cryptographic SRI
      if (sriHash) return true;
      const parsed = new URL(entryUrl, window.location.origin);
      return (
        parsed.hostname === window.location.hostname ||
        parsed.hostname === 'localhost' ||
        parsed.hostname === '127.0.0.1'
      );
    } catch {
      return false;
    }
  }, [entryUrl, sriHash]);


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

        // [D2] Trust-tier classification for this entry.
        const isRemotePinned = !!sriHash;

        // Resolve the trust tier for an already-validated manifest.
        //   signature present -> server-side publisher verification
        //   no signature      -> ONLY locally-served modules qualify, as
        //                        'unsigned-local' (read-only host APIs).
        async function resolveTier(manifestObj: any): Promise<ExtensionTier> {
          if (!manifestObj.signature) {
            if (!isRemotePinned) return 'unsigned-local';
            throw { kind: 'publisher', reason: 'remote-without-signature' };
          }
          try {
            const res = await fetch('/api/v1/extensions/verify-publisher', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ manifest: manifestObj }),
            });
            const data = await res.json();
            if (res.ok && data.valid) {
              // [Trust hardening] The BACKEND's classification is the ONLY
              // authority. A signed manifest cannot self-promote to
              // 'official' via its own tier field — that field is ignored.
              if (data.tier === 'official' || data.tier === 'community') {
                return data.tier;
              }
              throw { kind: 'publisher', reason: 'unrecognized-backend-tier' };
            }
            throw { kind: 'publisher', reason: data.reason || 'signature-mismatch' };
          } catch (err: any) {
            if (err && err.kind === 'publisher') throw err;
            // Server unreachable: fail-closed for remote modules; local dev
            // degrades to the restricted unsigned-local surface.
            if (!isRemotePinned) return 'unsigned-local';
            throw { kind: 'publisher', reason: 'verification-unavailable' };
          }
        }

        // If SRI hash is provided, enforce byte-level integrity verification
        if (isRemotePinned) {
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

          // J1 Hardening: Pre-execution Manifest Verification.
          // Untrusted remote code must NEVER be dynamically evaluated without a cryptographically valid pre-execution manifest.
          const sourceText = new TextDecoder().decode(buffer);
          let extractedManifest: any = null;
          try {
            const match = sourceText.match(/(?:export\s+)?(?:const|let|var)?\s*manifest\s*=\s*(\{[\s\S]*?\n\s*\});?/);
            if (match) {
              extractedManifest = JSON.parse(match[1]);
            }
          } catch {
            // Static regex parse failed
          }

          let preManifest = extractedManifest;
          if (!preManifest) {
            try {
              const manifestUrl = entryUrl.replace(/\.[^/.]+$/, '') + '.manifest.json';
              const mRes = await fetch(manifestUrl);
              if (mRes.ok) {
                preManifest = await mRes.json();
              }
            } catch {
              // Manifest file fetch fallback failed
            }
          }

          if (!preManifest) {
            if (active) {
              setLoadingState({
                status: 'contract_violation',
                violations: [
                  "Pre-execution verification failed: Remote extension must supply a statically verifiable signed manifest prior to module execution."
                ]
              });
            }
            return;
          }

          const preViolations = validateExtensionManifest(preManifest, { requireSignature: true });
          if (preViolations.length > 0) {
            if (active) setLoadingState({ status: 'contract_violation', violations: preViolations });
            return;
          }
          const tier = await resolveTier(preManifest);

          // Integrity and contract validated: instantiate via ephemeral Blob URL
          const blob = new Blob([buffer], { type: 'text/javascript' });
          blobUrlToRevoke = URL.createObjectURL(blob);
          const mod = await import(/* @vite-ignore */ blobUrlToRevoke);
          const manifestObj = (mod as any)?.manifest || preManifest;

          // Mandatory manifest confirmation post-import
          const violations = validateExtensionManifest(manifestObj, { requireSignature: true });
          if (violations.length > 0) {
            console.error(`[ExtensionHost] Contract violations for ${entryUrl}:`, violations);
            if (active) setLoadingState({ status: 'contract_violation', violations });
            return;
          }

          const ResolvedComp = mod.default || mod[Object.keys(mod)[0]] || mod;
          if (active) setLoadingState({ status: 'ready', Component: ResolvedComp, tier, manifest: manifestObj });
        } else {
          // Local/trusted-origin ESM without SRI pin. [D2] The manifest is
          // MANDATORY here too — an anonymous module can never be mounted.
          const mod = await import(/* @vite-ignore */ entryUrl);
          const manifestObj = (mod as any)?.manifest;

          const violations = !manifestObj
            ? [
                "Module exports no 'manifest' — every extension must declare its identity, capabilities and host-API usage (RuntimeExtension contract).",
              ]
            : validateExtensionManifest(manifestObj, { requireSignature: false });
          if (violations.length > 0 && active) {
            setLoadingState({ status: 'contract_violation', violations });
            return;
          }

          const tier = await resolveTier(manifestObj);
          const ResolvedComp = mod.default || mod[Object.keys(mod)[0]] || mod;
          if (active) setLoadingState({ status: 'ready', Component: ResolvedComp, tier, manifest: manifestObj });
        }
      } catch (err: any) {
        console.error(`[ZeroTrust Loader] Error mounting module ${entryUrl}:`, err);
        if (!active) return;
        if (err && err.kind === 'publisher') {
          // [P1.7/V06] Publisher verification failures carry a structured
          // `reason` (not a `message`). They must surface as the actionable
          // publisher_failed state; routing them through load_error hid the
          // actual trust failure from operators.
          setLoadingState({
            status: 'publisher_failed',
            publisherReason: String(err.reason || 'unknown'),
          });
          return;
        }
        setLoadingState({
          status: 'load_error',
          errorMessage: err?.message || 'Module evaluation failed.',
        });
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
      <ExtensionLoadError
        title="Untrusted Extension Origin Blocked"
        entryUrl={entryUrl}
        message="Module origin is outside the trusted domain policy and was blocked by Zero-Trust security rules."
      />
    );
  }

  if (loadingState.status === 'sri_failed') {
    return (
      <ExtensionLoadError
        title="Subresource Integrity (SRI) Violation"
        entryUrl={entryUrl}
        violations={[
          `Expected: ${sriHash}`,
          `Actual: ${loadingState.computedDigest}`,
        ]}
        message="Cryptographic integrity mismatch detected. Execution blocked to prevent tamper attacks."
      />
    );
  }

  if (loadingState.status === 'publisher_failed') {
    return (
      <ExtensionLoadError
        title="Publisher Verification Failed"
        entryUrl={entryUrl}
        violations={[`Reason: ${loadingState.publisherReason}`]}
        message="The manifest signature could not be verified against the runtime trust root. Unsigned LOCAL extensions are limited to read-only APIs; remote extensions require a verified publisher."
      />
    );
  }

  if (loadingState.status === 'contract_violation') {
    return (
      <ExtensionLoadError
        title={`Extension Contract Violation (api ${EXTENSION_CONTRACT_VERSION})`}
        entryUrl={entryUrl}
        violations={loadingState.violations}
        message="SRI proves bytes, not trust: extensions must present a signed manifest with declared capabilities."
      />
    );
  }

  if (loadingState.status === 'load_error') {
    return (
      <ExtensionLoadError
        title="Failed to Load Extension Module"
        entryUrl={entryUrl}
        message={loadingState.errorMessage}
      />
    );
  }

  if (loadingState.status === 'ready' && loadingState.Component) {
    const Component = loadingState.Component;
    const tier: ExtensionTier = loadingState.tier ?? 'unsigned-local';
    return (
      <ExtensionHostProvider tier={tier} manifest={loadingState.manifest}>

        {tier === 'unsigned-local' && (
          <div className="bg-amber-500/10 border-b border-amber-500/20 px-6 py-2 flex items-center gap-2 text-[10px] text-amber-300 font-medium shrink-0">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            <span>
              LOCAL EXTENSION — unsigned. Mounted with READ-ONLY host APIs only;
              routes/nav contributions are flagged in navigation.
            </span>
          </div>
        )}
        <RemoteErrorBoundary entryUrl={entryUrl}>
          <Component />
        </RemoteErrorBoundary>
      </ExtensionHostProvider>
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

const ConsoleLayout: React.FC = () => {

  const location = useLocation();
  // [P1-15] RBAC is presentation gating only. The role shown here comes from
  // the server (/api/auth/me); there is no client-side persona switching.
  const { user, role, canAccessSettings, canEditScenario, canSignCert } = useRBAC();
  const [isCmdOpen, setIsCmdOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [toasts, setToasts] = useState<{ id: string; message: string; type: string }[]>([]);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    Verify: true,
    Author: true,
    Inspect: true,
    Audit: true,
    Advanced: false,
    System: true,
  });

  // Authoritative RuntimeHealth (P0-1) + operating mode (P0-5).
  const {
    data: runtimeHealth,
    error: healthError,
  } = useQuery({
    queryKey: ['runtime-health'],
    queryFn: async () => {
      const res = await fetch('/api/status');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: 30_000,
    retry: 1,
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
    const handleToast = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      const id = Math.random().toString(36).substr(2, 9);
      setToasts(prev => [...prev, { id, ...detail }]);
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id));
      }, 4000);
    };

    window.addEventListener('agentv-toast', handleToast);

    // [N2 Global Network & Auth Signaling Interceptor]
    const originalFetch = window.fetch;
    window.fetch = async (...args) => {
      try {
        const response = await originalFetch(...args);
        if (response.status === 401 || response.status === 403) {
          const urlStr = typeof args[0] === 'string' ? args[0] : (args[0] as Request)?.url || '';
          const isSameOrigin = urlStr.startsWith('/') || (typeof window !== 'undefined' && urlStr.startsWith(window.location.origin));
          if (isSameOrigin && (urlStr.includes('/api/auth') || urlStr.includes('/api/v1/') || urlStr.includes('/v1/'))) {
            window.dispatchEvent(
              new CustomEvent('agentv-toast', {
                detail: {
                  type: 'error',
                  title: 'Authentication Failure',
                  message: 'Invalid or expired API credentials. Please re-authenticate.',
                },
              })
            );
          }
        }
        return response;
      } catch (err: any) {
        const urlStr = typeof args[0] === 'string' ? args[0] : (args[0] as Request)?.url || '';
        const isSameOrigin = urlStr.startsWith('/') || (typeof window !== 'undefined' && urlStr.startsWith(window.location.origin));
        if (isSameOrigin) {
          window.dispatchEvent(
            new CustomEvent('agentv-toast', {
              detail: {
                type: 'error',
                title: 'Harness Connection Error',
                message: err?.message || 'Failed to communicate with AgentV Console API backend.',
              },
            })
          );
        }
        throw err;
      }
    };

    return () => {
      window.removeEventListener('agentv-toast', handleToast);
      window.fetch = originalFetch;
    };
  }, []);


  const toggleGroup = (title: string) => {
    setExpandedGroups(prev => ({ ...prev, [title]: !prev[title] }));
  };

  // [G6] Navigation is organized around user jobs, not internal feature
  // names. Primary jobs are expanded by default; power tools live in the
  // collapsed "Advanced" group and stay reachable via routes/⌘K.
  const baseNavGroups: NavGroup[] = [
    {
      title: 'Verify',
      items: [
        { name: 'New Verification', path: '/', icon: <Home className="w-4 h-4" /> },
      ],
    },
    {
      title: 'Author',
      items: [
        { name: 'Scenario Library', path: '/scenarios', icon: <FileText className="w-4 h-4" /> },
        { name: 'Visual Composer', path: '/editor', icon: <Activity className="w-4 h-4" /> },
      ],
    },
    {
      title: 'Inspect',
      items: [
        { name: 'Runs & History', path: '/reports', icon: <BarChart2 className="w-4 h-4" /> },
        { name: 'Live Debugger', path: '/debugger', icon: <Play className="w-4 h-4" /> },
      ],
    },
    {
      title: 'Audit',
      items: [
        { name: 'Evidence Packages & Certs', path: '/reports?view=packages', icon: <FileText className="w-4 h-4" /> },
        { name: 'Trust Center', path: '/trust', icon: <ShieldCheck className="w-4 h-4" /> },
      ],
    },
    {
      title: 'Advanced',
      items: [
        { name: 'Triage Center', path: '/triage', icon: <AlertTriangle className="w-4 h-4" /> },
        { name: 'Adversarial Mutator', path: '/mutator', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Spec-to-Eval Importer', path: '/spec-import', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Failure Corpus', path: '/failures', icon: <ChevronRight className="w-3.5 h-3.5" /> },
      ],
    },
    {
      title: 'System',
      items: [
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
    if (item.path === '/trust' && !canSignCert) return true;
    if (item.path === '/mutator' && !canEditScenario) return true;
    return false;
  };

  const roleColors: Record<string, string> = {
    'System Admin': 'text-indigo-400 bg-indigo-500/10 border-indigo-500/20',
    'Compliance Auditor': 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20',
    'Scenario Designer': 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
    'MultiAgentOps Eng.': 'text-amber-400 bg-amber-500/10 border-amber-500/20',
    'Viewer': 'text-slate-400 bg-slate-500/10 border-slate-500/20',
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
                      const currentUrl = location.pathname + location.search;
                      const isActive = item.path.includes('?')
                        ? currentUrl === item.path
                        : location.pathname === item.path && (!location.search || !location.search.includes('view='));
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
                            className="flex items-center gap-3 px-3 py-2 rounded-lg text-xs border border-transparent text-slate-400 hover:text-white hover:bg-slate-900/60 transition-all group"
                          >
                            <div className="shrink-0 group-hover:scale-110 transition-transform">{item.icon}</div>
                            {!sidebarCollapsed && <span className="truncate">{item.name}</span>}
                            {!sidebarCollapsed && <ExternalLink className="w-3 h-3 ml-auto opacity-50" />}
                          </a>
                        );
                      }

                      return (
                        <Link
                          key={item.id || item.name}
                          to={item.path}
                          className={`flex items-center gap-3 px-3 py-2 rounded-lg text-xs transition-all ${isActive
                            ? 'bg-indigo-600/10 text-indigo-400 border border-indigo-500/20 font-semibold'
                            : 'text-slate-400 hover:text-white hover:bg-slate-900/60 border border-transparent'
                            }`}
                        >
                          <div className="shrink-0">{item.icon}</div>
                          {!sidebarCollapsed && <span className="truncate">{item.name}</span>}
                          {!sidebarCollapsed && item.badge && (
                            <span className="ml-auto px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                              {item.badge}
                            </span>
                          )}
                          {!sidebarCollapsed && !item.badge && item.tier === 'local' && (
                            <span
                              title="[D2] Unsigned/local extension: read-only host APIs only."
                              className="ml-auto px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider bg-amber-500/15 text-amber-300 border border-amber-500/30"
                            >
                              LOCAL
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

        {/* Global User Profile Footer */}
        <div className="p-3 border-t border-slate-900 bg-slate-950/20">
          <div className="flex items-center justify-between gap-2">
            {!sidebarCollapsed && (
              <div className="flex flex-col min-w-0">
                <span className="text-[11px] font-bold text-slate-300 truncate">{user?.name || 'Local Operator'}</span>
                <span className="text-[9px] font-mono text-slate-500 truncate">{user?.id || 'dev@local'}</span>
              </div>
            )}
            <span
              className={`px-2 py-0.5 rounded text-[9px] font-mono uppercase font-bold border shrink-0 ${roleColors[role] || 'text-slate-400'
                }`}
            >
              {sidebarCollapsed ? role[0] : role}
            </span>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Operational Bar */}
        <header className="h-14 border-b border-slate-900 bg-slate-950/40 flex items-center justify-between px-6 shrink-0">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setIsCmdOpen(true)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/80 hover:bg-slate-900 border border-slate-800 text-xs text-slate-400 hover:text-white transition-all shadow-inner"
            >
              <Terminal className="w-3.5 h-3.5 text-indigo-400" />
              <span>Search actions...</span>
              <kbd className="text-[9px] font-mono bg-slate-950 px-1.5 py-0.5 rounded border border-slate-800 text-slate-500">
                ⌘K
              </kbd>
            </button>
          </div>

          <div className="flex items-center gap-3">
            {/* Authoritative Runtime Health (P0-1): server-derived only.
                Never render READY without a successful health verification. */}
            {(() => {
              const h = runtimeHealth;
              const status = healthError
                ? 'UNREACHABLE'
                : (h?.status as string | undefined) ?? 'UNREACHABLE';
              const cls =
                status === 'HEALTHY'
                  ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                  : status === 'DEGRADED'
                    ? 'bg-amber-500/10 border-amber-500/20 text-amber-400'
                    : 'bg-red-500/10 border-red-500/20 text-red-400';
              const dotCls =
                status === 'HEALTHY'
                  ? 'bg-emerald-400 animate-pulse'
                  : status === 'DEGRADED'
                    ? 'bg-amber-400'
                    : 'bg-red-500';
              const label =
                status === 'HEALTHY' ? 'RUNTIME READY' : `RUNTIME ${status}`;
              const title = [
                `mode: ${h?.mode ?? 'unknown'}`,
                `version: ${h?.version ?? '?'}`,
                `heartbeat: ${h?.last_heartbeat ?? 'never'}`,
                ...Object.entries(h?.dependencies ?? {}).map(
                  ([k, v]) => `${k}: ${v}`
                ),
                ...(h?.details ?? []),
              ].join('\n');
              return (
                <div
                  title={title}
                  className={`flex items-center gap-2 px-2.5 py-1 rounded-full border text-[10px] font-mono cursor-help ${cls}`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${dotCls}`} />
                  <span>{label}</span>
                </div>
              );
            })()}
          </div>
        </header>

        {/* Demo-mode banner (P0-5): production never shows it. */}
        {runtimeHealth?.mode === 'demo' && (
          <div className="px-6 py-1.5 bg-amber-500/10 border-b border-amber-500/20 text-[11px] font-mono text-amber-300 flex items-center gap-2">
            🔬 DEMO MODE — sample data & simulated executions. This is not independent
            verification of your agent.
          </div>
        )}


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

const RemoteRouteGuard: React.FC<{ item: any }> = ({ item }) => {
  const { role, hasPermission } = useRBAC();
  const requiredRole = item.required_role || item.role;
  const requiredPerm = item.required_permission || item.permission;

  if (requiredRole && role !== 'System Admin' && role !== requiredRole) {
    return (
      <div className="p-8 text-center text-slate-400">
        <h3 className="text-lg font-bold text-red-400 mb-2">Access Denied</h3>
        <p className="text-sm">Role '{requiredRole}' is required to access this extension view.</p>
      </div>
    );
  }

  if (requiredPerm && !hasPermission(requiredPerm)) {
    return (
      <div className="p-8 text-center text-slate-400">
        <h3 className="text-lg font-bold text-red-400 mb-2">Access Denied</h3>
        <p className="text-sm">Permission '{requiredPerm}' is required to access this extension view.</p>
      </div>
    );
  }

  return (
    <RemoteComponentLoader
      entryUrl={item.remoteEntry}
      sriHash={item.sriHash || item.integrity || item.sri}
    />
  );
};

export function ConsoleRoutes() {
  const { data: remoteNav } = useQuery({
    queryKey: ['console-nav-registry'],
    queryFn: async () => {
      const res = await fetch('/api/nav');
      if (!res.ok) return null;
      const data = await res.json();
      return Array.isArray(data) ? data : data.nav || [];
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
        {/* Primary Product Spine (P1-12): Connect → Verify → Diagnose */}
        <Route path="/" element={<VerificationWorkflowPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />

        {/* Runtime OSS Core Screens */}
        <Route path="/scenarios" element={<ScenarioLibraryPage />} />
        <Route path="/scenarios/compose" element={<ScenarioComposerPage />} />
        <Route path="/editor" element={<ScenarioComposerPage />} />
        {/* [G1] The standalone runner page was folded into the verification
            workflow's Advanced execution settings drawer. Old /runner links
            redirect to the primary spine. */}
        <Route path="/runner" element={<Navigate to="/" replace />} />
        <Route path="/debugger" element={<LiveDebuggerPage />} />
        <Route path="/reports" element={<RunsReportsPage />} />
        <Route path="/runs" element={<RunsReportsPage />} />
        <Route path="/evidence" element={<RunsReportsPage />} />
        <Route path="/evidence/packages" element={<RunsReportsPage />} />
        <Route path="/trust" element={<TrustCenterPage />} />
        <Route path="/docs" element={<DocsPage />} />
        <Route path="/settings" element={<SettingsPage />} />

        {/* Runtime OSS Diagnostics & Tooling */}
        <Route path="/spec-import" element={<SpecToEvalImporter />} />
        <Route path="/mutator" element={<AdversarialMutator />} />
        <Route path="/failures" element={<FailureCorpus />} />
        <Route path="/triage" element={<Triage />} />

        {/* Dynamic Micro-Frontend Remote Routes (Control Plane extensions).
            Enterprise routes are NOT declared in OSS; they exist only when a
            signed extension manifest contributes them via /api/nav. */}
        {remoteRoutes.map((item: any) => (
          <Route
            key={item.path}
            path={item.path.startsWith('/') ? item.path : `/${item.path}`}
            element={<RemoteRouteGuard item={item} />}
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
          <ConsoleRoutes />
        </BrowserRouter>
      </RBACProvider>
    </QueryClientProvider>
  );
}

export default App;

