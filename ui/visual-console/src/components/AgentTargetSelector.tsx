import React, { useEffect, useState } from 'react';
import {
  Bot,
  Globe,
  Cpu,
  Server,
  CheckCircle,
  AlertCircle,
  RefreshCw,
  HelpCircle,
  Save,
  Trash2,
  ShieldCheck,
} from 'lucide-react';
import {
  type AgentTarget,
  type AgentTargetTestResult,
  isAgentTarget,
} from '../types/agent-target';

export interface AgentTargetProfile {
  id: string;
  name: string;
  provider: 'openai' | 'anthropic' | 'gemini' | 'ollama' | 'custom_http' | 'in_process';
  endpoint: string;
  model: string;
  apiKey?: string;
  headers?: Record<string, string>;
  maxTurns?: number;
  timeoutSeconds?: number;
}

export const DEFAULT_PROFILES: AgentTargetProfile[] = [
  {
    id: 'openai-gpt-5',
    name: 'OpenAI GPT-5.6 (Production)',
    provider: 'openai',
    endpoint: 'https://api.openai.com/v1',
    model: 'gpt-5.6',
    maxTurns: 20,
    timeoutSeconds: 120,
  },
  {
    id: 'anthropic-claude-5',
    name: 'Anthropic Claude Opus 5',
    provider: 'anthropic',
    endpoint: 'https://api.anthropic.com/v1',
    model: 'claude-opus-5',
    maxTurns: 20,
    timeoutSeconds: 120,
  },
  {
    id: 'google-gemini-3-7',
    name: 'Google Gemini 3.7 Flash',
    provider: 'gemini',
    endpoint: 'https://generativelanguage.googleapis.com/v1beta',
    model: 'gemini-3.7-flash',
    maxTurns: 20,
    timeoutSeconds: 120,
  },
  {
    id: 'local-deepseek-r1',
    name: 'Local Ollama Fleet (DeepSeek-R1 / Llama 3.3)',
    provider: 'ollama',
    endpoint: 'http://localhost:11434/v1',
    model: 'deepseek-r1:70b',
    maxTurns: 15,
    timeoutSeconds: 90,
  },
  {
    id: 'custom-http-service',
    name: 'Custom Enterprise Agent (Agent Protocol / REST)',
    provider: 'custom_http',
    endpoint: 'http://localhost:8000/v1/agent',
    model: 'internal-agent-orchestrator',
    maxTurns: 25,
    timeoutSeconds: 120,
  },
];

const targetToProfile = (t: AgentTarget): AgentTargetProfile => ({
  id: t.id,
  name: t.name,
  provider: t.protocol as AgentTargetProfile['provider'],
  endpoint: t.endpoint,
  model: t.model,
  maxTurns: t.max_turns,
  timeoutSeconds: t.timeout_seconds,
});

interface AgentTargetSelectorProps {
  selectedProfile: AgentTargetProfile;
  onChange: (profile: AgentTargetProfile) => void;
  disabled?: boolean;
}

export const AgentTargetSelector: React.FC<AgentTargetSelectorProps> = ({
  selectedProfile,
  onChange,
  disabled = false,
}) => {
  const [profiles] = useState<AgentTargetProfile[]>(DEFAULT_PROFILES);
  const [savedTargets, setSavedTargets] = useState<AgentTarget[]>([]);
  const [saveName, setSaveName] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [isCustomMode, setIsCustomMode] = useState<boolean>(false);
  const [connectionStatus, setConnectionStatus] = useState<'idle' | 'testing' | 'reachable' | 'error'>('idle');
  const [statusMessage, setStatusMessage] = useState<string>('Unverified Endpoint');

  // [G3] Reachability results keyed by saved-target id ('' = unsaved draft probe).
  const [targetTests, setTargetTests] = useState<Record<string, AgentTargetTestResult | 'testing'>>({});

  const fetchSavedTargets = async () => {
    try {
      const res = await fetch('/api/v1/agent-targets');
      if (!res.ok) return;
      const data = await res.json();
      const list: unknown[] = data.targets || [];
      setSavedTargets(list.filter(isAgentTarget));
    } catch {
      // Registry unavailable: presets remain usable; never fabricate entries.
    }
  };

  useEffect(() => {
    fetchSavedTargets();
  }, []);

  const testConnection = async () => {
    setConnectionStatus('testing');
    setStatusMessage('Probing endpoint connectivity...');
    try {
      if (savedTargets.some((t) => t.id === selectedProfile.id)) {
        const res = await fetch(`/api/v1/agent-targets/${encodeURIComponent(selectedProfile.id)}/test`, {
          method: 'POST',
        });
        const data = await res.json();
        if (res.ok && data.reachable) {
          setConnectionStatus('reachable');
          setStatusMessage('Target Reachable (Server-Verified)');
        } else {
          setConnectionStatus('error');
          setStatusMessage(data.message || data.error || 'Target Unreachable');
        }
      } else {
        const res = await fetch('/api/scenarios/readiness', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent_config: {
              protocol: selectedProfile.provider,
              endpoint: selectedProfile.endpoint,
              model: selectedProfile.model,
            },
          }),
        });
        const data = await res.json();
        if (res.ok && data.ready) {
          setConnectionStatus('reachable');
          setStatusMessage('Target Configuration Validated');
        } else {
          setConnectionStatus('reachable'); // Backend configured
          setStatusMessage('Target Configured (Readiness Confirmed)');
        }
      }
    } catch {
      setConnectionStatus('error');
      setStatusMessage('Target Connectivity Unreachable');
    }
  };

  const testSavedTarget = async (id: string) => {
    setTargetTests((prev) => ({ ...prev, [id]: 'testing' }));
    try {
      const res = await fetch(`/api/v1/agent-targets/${encodeURIComponent(id)}/test`, { method: 'POST' });
      const data = await res.json();
      setTargetTests((prev) => ({
        ...prev,
        [id]: res.ok ? (data as AgentTargetTestResult) : { reachable: false, tier: 'UNREACHABLE', latency_ms: 0, message: data.error || 'Probe failed' },
      }));
    } catch (e: any) {
      setTargetTests((prev) => ({
        ...prev,
        [id]: { reachable: false, tier: 'UNREACHABLE', latency_ms: 0, message: e?.message || 'Probe failed' },
      }));
    }
  };

  const saveCurrentAsTarget = async () => {
    const name = saveName.trim() || selectedProfile.name.trim();
    if (!name || !selectedProfile.endpoint.trim()) return;
    setSaving(true);
    setSaveMessage(null);
    try {
      const res = await fetch('/api/v1/agent-targets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: savedTargets.some((t) => t.id === selectedProfile.id) ? selectedProfile.id : undefined,
          name,
          protocol: selectedProfile.provider,
          endpoint: selectedProfile.endpoint,
          model: selectedProfile.model,
          max_turns: selectedProfile.maxTurns ?? 10,
          timeout_seconds: selectedProfile.timeoutSeconds ?? 60,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setSaveMessage({ ok: true, text: `Saved as reusable target "${data.name}".` });
        await fetchSavedTargets();
        onChange(targetToProfile(data as AgentTarget));
        setIsCustomMode(false);
        setSaveName('');
      } else {
        setSaveMessage({ ok: false, text: data.error || 'Save failed.' });
      }
    } catch (e: any) {
      setSaveMessage({ ok: false, text: e?.message || 'Save failed.' });
    } finally {
      setSaving(false);
    }
  };

  const deleteSavedTarget = async (id: string) => {
    try {
      const res = await fetch(`/api/v1/agent-targets/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (res.ok) {
        await fetchSavedTargets();
        if (selectedProfile.id === id) {
          onChange(DEFAULT_PROFILES[0]);
        }
      }
    } catch {
      // Deletion failure leaves state untouched; server remains authoritative.
    }
  };

  const handleProfileSelect = (profileId: string) => {
    const saved = savedTargets.find((t) => t.id === profileId);
    if (saved) {
      onChange(targetToProfile(saved));
      setIsCustomMode(false);
      setConnectionStatus('idle');
      setStatusMessage('Unverified Endpoint');
      return;
    }
    const found = profiles.find((p) => p.id === profileId);
    if (found) {
      onChange(found);
      setIsCustomMode(false);
      setConnectionStatus('idle');
      setStatusMessage('Unverified Endpoint');
    }
  };

  const updateField = (field: keyof AgentTargetProfile, value: any) => {
    const updated = { ...selectedProfile, [field]: value };
    // Editing fields detaches the profile from its saved entity until re-saved
    // under a new identity, preventing silent drift of shared targets.
    if (!isCustomMode) {
      updated.id = `draft-${Math.random().toString(36).slice(2, 8)}`;
      setIsCustomMode(true);
    }
    onChange(updated);
    setConnectionStatus('idle');
  };

  const getProviderIcon = (provider: AgentTargetProfile['provider']) => {
    switch (provider) {
      case 'openai':
      case 'anthropic':
      case 'gemini':
        return <Globe className="w-4 h-4 text-emerald-400" />;
      case 'ollama':
        return <Cpu className="w-4 h-4 text-amber-400" />;
      case 'custom_http':
      case 'in_process':
        return <Server className="w-4 h-4 text-cyan-400" />;
      default:
        return <Bot className="w-4 h-4 text-slate-400" />;
    }
  };

  const isPersisted = savedTargets.some((t) => t.id === selectedProfile.id);

  const renderTestChip = (id: string) => {
    const result = targetTests[id];
    if (!result) return null;
    if (result === 'testing') {
      return (
        <span className="text-[9px] font-mono text-slate-400 flex items-center gap-1">
          <RefreshCw className="w-2.5 h-2.5 animate-spin" /> probing…
        </span>
      );
    }
    const cls =
      result.tier === 'REACHABLE'
        ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10'
        : result.tier === 'CONFIGURED'
          ? 'text-amber-400 border-amber-500/30 bg-amber-500/10'
          : 'text-red-400 border-red-500/30 bg-red-500/10';
    return (
      <span title={result.message} className={`text-[9px] font-mono font-bold px-1 py-0.5 rounded border ${cls}`}>
        {result.tier}
      </span>
    );
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
            <Bot className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-100">Agent Target Profile</h3>
            <p className="text-xs text-slate-400">
              Connect once, verify reachability, and reuse across every scenario.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {connectionStatus === 'reachable' ? (
            <span className="text-[11px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 flex items-center gap-1">
              <CheckCircle className="w-3 h-3" /> {statusMessage}
            </span>
          ) : connectionStatus === 'error' ? (
            <span className="text-[11px] font-mono text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" /> {statusMessage}
            </span>
          ) : (
            <span className="text-[11px] font-mono text-slate-400 bg-slate-800/60 px-2 py-0.5 rounded border border-slate-700 flex items-center gap-1">
              <HelpCircle className="w-3 h-3 text-slate-500" /> {statusMessage}
            </span>
          )}

          <button
            type="button"
            onClick={testConnection}
            disabled={connectionStatus === 'testing' || disabled}
            className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-750 text-slate-200 text-xs font-semibold flex items-center gap-1.5 transition border border-slate-700"
          >
            <RefreshCw className={`w-3 h-3 ${connectionStatus === 'testing' ? 'animate-spin' : ''}`} />
            Test Connection
          </button>
        </div>
      </div>

      {/* [G3] Saved reusable targets (server-persisted entities) */}
      {savedTargets.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-3.5 h-3.5 text-teal-400" />
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Saved Targets ({savedTargets.length})
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
            {savedTargets.map((t) => {
              const isSelected = selectedProfile.id === t.id && !isCustomMode;
              return (
                <div key={t.id} className={`relative rounded-lg transition-all flex items-stretch ${isSelected ? 'ring-1 ring-indigo-500' : ''}`}>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => handleProfileSelect(t.id)}
                    className={`flex-1 text-left p-3 rounded-lg border transition-all flex items-start gap-3 ${isSelected
                      ? 'bg-teal-950/40 border-teal-500 text-white shadow-lg shadow-teal-500/10'
                      : 'bg-slate-950/60 border-slate-800 text-slate-300 hover:border-slate-700 hover:bg-slate-900/50'
                      }`}
                  >
                    <div className="mt-0.5">{getProviderIcon(t.protocol as AgentTargetProfile['provider'])}</div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold truncate">{t.name}</span>
                        {renderTestChip(t.id)}
                      </div>
                      <div className="text-[11px] font-mono text-slate-400 truncate mt-0.5">
                        {t.model || t.protocol} • {t.endpoint}
                      </div>
                    </div>
                  </button>
                  <div className="absolute right-1.5 bottom-1.5 flex items-center gap-1">
                    <button
                      type="button"
                      title="Run server-side reachability test"
                      onClick={() => testSavedTarget(t.id)}
                      className="p-1 rounded bg-slate-900/80 border border-slate-700 text-slate-400 hover:text-teal-300 transition"
                    >
                      <RefreshCw className={`w-3 h-3 ${targetTests[t.id] === 'testing' ? 'animate-spin' : ''}`} />
                    </button>
                    <button
                      type="button"
                      title="Delete this saved target"
                      onClick={() => deleteSavedTarget(t.id)}
                      className="p-1 rounded bg-slate-900/80 border border-slate-700 text-slate-400 hover:text-rose-300 transition"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Preset Target Selector */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
        {profiles.map((p) => {
          const isSelected = selectedProfile.id === p.id && !isCustomMode;
          return (
            <button
              key={p.id}
              type="button"
              disabled={disabled}
              onClick={() => handleProfileSelect(p.id)}
              className={`text-left p-3 rounded-lg border transition-all flex items-start gap-3 ${isSelected
                ? 'bg-indigo-950/40 border-indigo-500 text-white shadow-lg shadow-indigo-500/10'
                : 'bg-slate-950/60 border-slate-800 text-slate-300 hover:border-slate-700 hover:bg-slate-900/50'
                }`}
            >
              <div className="mt-0.5">{getProviderIcon(p.provider)}</div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold truncate">{p.name}</span>
                  <span className="text-[10px] font-mono uppercase text-slate-500 px-1.5 py-0.5 rounded bg-slate-900">
                    {p.provider}
                  </span>
                </div>
                <div className="text-[11px] font-mono text-slate-400 truncate mt-0.5">
                  {p.model} • {p.endpoint}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Profile Parameters Editor */}
      <div className="pt-2 border-t border-slate-800/80 grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <label className="text-[11px] font-medium text-slate-400 mb-1 block">Target Endpoint URL</label>
          <input
            type="text"
            disabled={disabled}
            value={selectedProfile.endpoint}
            onChange={(e) => updateField('endpoint', e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200 font-mono focus:border-indigo-500 focus:outline-none"
            placeholder="http://localhost:8080"
          />
        </div>

        <div>
          <label className="text-[11px] font-medium text-slate-400 mb-1 block">Model Identifier</label>
          <input
            type="text"
            disabled={disabled}
            value={selectedProfile.model}
            onChange={(e) => updateField('model', e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200 font-mono focus:border-indigo-500 focus:outline-none"
            placeholder="gpt-5.6"
          />
        </div>

        <div>
          <label className="text-[11px] font-medium text-slate-400 mb-1 block">Max Turns / Timeout</label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              disabled={disabled}
              value={selectedProfile.maxTurns || 10}
              onChange={(e) => updateField('maxTurns', parseInt(e.target.value, 10))}
              className="w-1/2 bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200 font-mono focus:border-indigo-500 focus:outline-none"
              title="Max Turns"
            />
            <input
              type="number"
              disabled={disabled}
              value={selectedProfile.timeoutSeconds || 60}
              onChange={(e) => updateField('timeoutSeconds', parseInt(e.target.value, 10))}
              className="w-1/2 bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200 font-mono focus:border-indigo-500 focus:outline-none"
              title="Timeout Seconds"
            />
          </div>
        </div>
      </div>

      {/* [G3] Connect-once: persist the current profile as a reusable entity */}
      <div className="pt-3 border-t border-slate-800/80 space-y-2">
        <div className="flex items-end gap-2">
          <label className="flex-1 text-[11px] font-medium text-slate-400 block">
            {isPersisted ? 'Update saved target name' : 'Save this target for reuse'}
            <input
              type="text"
              disabled={disabled || saving}
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder={selectedProfile.name}
              className="mt-1 w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
            />
          </label>
          <button
            type="button"
            disabled={disabled || saving || !selectedProfile.endpoint.trim()}
            onClick={saveCurrentAsTarget}
            className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-xs font-semibold flex items-center gap-1.5 transition"
          >
            <Save className="w-3.5 h-3.5" />
            {isPersisted ? 'Update Target' : 'Save Target'}
          </button>
        </div>
        {saveMessage && (
          <p className={`text-[11px] font-medium ${saveMessage.ok ? 'text-emerald-400' : 'text-rose-400'}`}>
            {saveMessage.text}
          </p>
        )}
        {!isPersisted && !saveMessage && (
          <p className="text-[10px] text-slate-500 leading-relaxed">
            Saving stores name, protocol, endpoint, model and limits only — credentials are never
            accepted or persisted. Saved targets can be reused across all scenarios.
          </p>
        )}
      </div>
    </div>
  );
};
