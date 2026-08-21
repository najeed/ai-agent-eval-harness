import React, { useState } from 'react';
import { Bot, Cpu, Globe, Server, CheckCircle } from 'lucide-react';

export interface AgentTargetProfile {
  id: string;
  name: string;
  provider: 'openai' | 'anthropic' | 'gemini' | 'ollama' | 'custom_http' | 'in_process';
  endpoint: string;
  model: string;
  authHeader?: string;
  protocol: 'http' | 'socket' | 'custom_grpc';
  maxTurns?: number;
  timeoutSeconds?: number;
  temperature?: number;
}

export const DEFAULT_PROFILES: AgentTargetProfile[] = [
  {
    id: 'openai-gpt-5',
    name: 'OpenAI GPT-5.6 (Production)',
    provider: 'openai',
    endpoint: 'https://api.openai.com/v1',
    model: 'gpt-5.6',
    protocol: 'http',
    temperature: 0.0,
    maxTurns: 15,
    timeoutSeconds: 90,
  },
  {
    id: 'anthropic-claude-5',
    name: 'Anthropic Claude Opus 5',
    provider: 'anthropic',
    endpoint: 'https://api.anthropic.com/v1',
    model: 'claude-opus-5',
    protocol: 'http',
    temperature: 0.0,
    maxTurns: 15,
    timeoutSeconds: 90,
  },
  {
    id: 'google-gemini-3-7',
    name: 'Google Gemini 3.7 Flash',
    provider: 'gemini',
    endpoint: 'https://googleapis.com',
    model: 'gemini-3.7-flash',
    protocol: 'http',
    temperature: 0.0,
    maxTurns: 15,
    timeoutSeconds: 90,
  },
  {
    id: 'local-deepseek-r1',
    name: 'Local Ollama Fleet (DeepSeek-R1 / Llama 3.3)',
    provider: 'ollama',
    endpoint: 'http://localhost:11434',
    model: 'deepseek-r1:70b',
    protocol: 'http',
    temperature: 0.0,
    maxTurns: 12,
    timeoutSeconds: 120,
  },
  {
    id: 'custom-http-service',
    name: 'Custom Enterprise Agent (Agent Protocol / REST)',
    provider: 'custom_http',
    endpoint: 'http://localhost:8080/v1/agent',
    model: 'internal-agent-orchestrator',
    protocol: 'http',
    maxTurns: 20,
    timeoutSeconds: 120,
  },
];



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
  const [isCustomMode, setIsCustomMode] = useState<boolean>(false);


  const handleProfileSelect = (profileId: string) => {
    const found = profiles.find((p) => p.id === profileId);
    if (found) {
      onChange(found);
      setIsCustomMode(false);
    }
  };

  const updateField = (field: keyof AgentTargetProfile, value: any) => {
    const updated = { ...selectedProfile, [field]: value };
    onChange(updated);
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
              Resolved connection, authentication, and execution boundary for evaluation.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 flex items-center gap-1">
            <CheckCircle className="w-3 h-3" /> Target Connected
          </span>
        </div>
      </div>

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
            placeholder="gpt-4o"
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
    </div>
  );
};
