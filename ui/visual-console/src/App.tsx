import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation, Outlet } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CommandPalette } from './components/CommandPalette';
import {
  Home, FileText, Play, Activity, BarChart2, ShieldCheck,
  Settings, BookOpen, ChevronDown, ChevronRight, Menu, HeartPulse,
  AlertTriangle, CheckCircle2, Server, Bell
} from 'lucide-react';
import { RBACProvider, useRBAC } from './context/RBACContext';
import type { UserRole } from './context/RBACContext';

// Import P1 Pages (we will create these next)
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

// Import P2 Shell Pages
import {
  SpecToEvalImporter, AdversarialMutator, TraceExplain
} from './pages/ShellPages';

const queryClient = new QueryClient();

// Nav Item structure
interface NavItem {
  name: string;
  path: string;
  icon: React.ReactNode;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

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

    const fetchStatus = async () => {
      try {
        const res = await fetch(`/api/publish/${jobId}`);
        if (res.ok) {
          const data = await res.json();
          setStatus(data.status);
          setProgress(data.progress);
        }
      } catch (e) {
        console.error(e);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, [jobId]);

  if (!jobId) return null;

  return (
    <div className="relative shrink-0">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="p-1.5 bg-slate-950 border border-slate-850 hover:border-slate-700 text-slate-450 hover:text-white rounded-lg transition-all flex items-center justify-center relative"
        title="Active Jobs Status"
      >
        <Bell className={`w-4 h-4 ${
          status === 'running' ? 'animate-bounce text-amber-400' :
          status === 'completed' ? 'text-emerald-400 font-bold' :
          status === 'failed' ? 'text-rose-400' : 'text-slate-400'
        }`} />
        {status === 'running' && (
          <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 bg-amber-500 rounded-full animate-ping" />
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-64 bg-slate-950 border border-slate-900 rounded-xl shadow-2xl p-4 z-50 space-y-3 animate-slide-in text-left">
          <div className="flex justify-between items-center border-b border-slate-900 pb-2">
            <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Active Conductor Job</span>
            <span className={`text-[8px] px-1.5 py-0.5 rounded font-extrabold uppercase ${
              status === 'completed' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
              status === 'failed' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' :
              'bg-amber-500/10 text-amber-400 border border-amber-500/20 animate-pulse'
            }`}>
              {status}
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
  const { role, setRole, canAccessSettings, canEditScenario, canRunEval, canSignCert } = useRBAC();
  const [isCmdOpen, setIsCmdOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [toasts, setToasts] = useState<{ id: string; message: string; type: string }[]>([]);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    Overview: true,
    Build: true,
    'Run & Verify': true,
    Analyze: false,
    'Publish & Integrate': false,
    System: true
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

  const navGroups: NavGroup[] = [
    {
      title: 'Overview',
      items: [
        { name: 'Dashboard', path: '/', icon: <Home className="w-4 h-4" /> }
      ]
    },
    {
      title: 'Build',
      items: [
        { name: 'Scenario Library', path: '/scenarios', icon: <FileText className="w-4 h-4" /> },
        { name: 'Scenario Composer', path: '/editor', icon: <Activity className="w-4 h-4" /> },
        { name: 'Spec-to-Eval Importer', path: '/spec-import', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Adversarial Mutator', path: '/mutator', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Auto-Translate', path: '/translate', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Calibration Console', path: '/calibration', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Registry Sync', path: '/sync', icon: <ChevronRight className="w-3.5 h-3.5" /> }
      ]
    },
    {
      title: 'Run & Verify',
      items: [
        { name: 'Evaluation Runner', path: '/runner', icon: <Play className="w-4 h-4" /> },
        { name: 'Live Trace Debugger', path: '/debugger', icon: <Activity className="w-4 h-4" /> },
        { name: 'Runs & Reports', path: '/reports', icon: <BarChart2 className="w-4 h-4" /> },
        { name: 'Trust Center', path: '/trust', icon: <ShieldCheck className="w-4 h-4" /> },
        { name: 'Trace Explain (AI)', path: '/explain', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'HITL Queue', path: '/hitl', icon: <ChevronRight className="w-3.5 h-3.5" /> }
      ]
    },
    {
      title: 'Analyze',
      items: [
        { name: 'Metrics & Leaderboards', path: '/metrics', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Failure Corpus Search', path: '/failures', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Triage Center', path: '/triage', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Benchmarks', path: '/benchmarks', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'Compliance & Forensics', path: '/compliance', icon: <ChevronRight className="w-3.5 h-3.5" /> }
      ]
    },
    {
      title: 'Publish & Integrate',
      items: [
        { name: 'Publication Suite', path: '/publish', icon: <ChevronRight className="w-3.5 h-3.5" /> },
        { name: 'CI/CD Integration', path: '/cicd', icon: <ChevronRight className="w-3.5 h-3.5" /> }
      ]
    },
    {
      title: 'System',
      items: [
        { name: 'Guides & Documentation', path: '/docs', icon: <BookOpen className="w-4 h-4" /> },
        { name: 'System & Health', path: '/settings', icon: <Settings className="w-4 h-4" /> }
      ]
    }
  ];

  // Role-based nav access gating
  const isNavItemRestricted = (path: string): boolean => {
    if (path === '/settings' && !canAccessSettings) return true;
    if (path === '/editor' && !canEditScenario) return true;
    if (path === '/runner' && !canRunEval) return true;
    if (path === '/trust' && !canSignCert) return true;
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
            const isExpanded = expandedGroups[group.title];
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
                      const isActive = location.pathname === item.path || (item.path !== '/' && location.pathname.startsWith(item.path));
                      const restricted = isNavItemRestricted(item.path);
                      return restricted ? (
                        <div
                          key={item.name}
                          title={`Restricted: insufficient role permissions`}
                          className="flex items-center gap-3 px-3 py-2 rounded-lg text-xs border border-transparent text-slate-600 opacity-50 cursor-not-allowed select-none"
                        >
                          <div className="shrink-0">{item.icon}</div>
                          {!sidebarCollapsed && <span className="truncate">{item.name}</span>}
                          {!sidebarCollapsed && <span className="ml-auto text-[8px] uppercase tracking-wider text-slate-600 font-bold">🔒</span>}
                        </div>
                      ) : (
                        <Link
                          key={item.name}
                          to={item.path}
                          className={`flex items-center gap-3 px-3 py-2 rounded-lg text-xs transition-all ${isActive
                              ? 'bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 font-bold'
                              : 'border border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/50'
                            }`}
                        >
                          <div className="shrink-0">{item.icon}</div>
                          {!sidebarCollapsed && <span className="truncate">{item.name}</span>}
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

            {/* Persona Switcher Dropdown */}
            <div className="flex items-center gap-1.5 border-l border-slate-900 pl-3">
              <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider font-sans">Role:</span>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as UserRole)}
                className="bg-slate-950 border border-slate-850 text-indigo-400 font-bold rounded px-2.5 py-1 text-[11px] focus:outline-none focus:border-indigo-500 font-sans cursor-pointer"
              >
                <option value="System Admin">System Admin</option>
                <option value="Compliance Auditor">Compliance Auditor</option>
                <option value="Scenario Designer">Scenario Designer</option>
                <option value="MultiAgentOps Eng.">MultiAgentOps Eng.</option>
              </select>
            </div>
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

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RBACProvider>
        <BrowserRouter basename="/v2">
          <Routes>
            <Route element={<ConsoleLayout />}>
              {/* P1 Main Screens */}
              <Route path="/" element={<DashboardPage />} />
              <Route path="/scenarios" element={<ScenarioLibraryPage />} />
              <Route path="/editor" element={<ScenarioComposerPage />} />
              <Route path="/runner" element={<EvaluationRunnerPage />} />
              <Route path="/debugger" element={<LiveDebuggerPage />} />
              <Route path="/reports" element={<RunsReportsPage />} />
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
            </Route>
          </Routes>
        </BrowserRouter>
      </RBACProvider>
    </QueryClientProvider>
  );
}

export default App;
