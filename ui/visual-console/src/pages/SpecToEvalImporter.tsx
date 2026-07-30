import React, { useState } from 'react';
import Editor from '@monaco-editor/react';
import { FileText, PlayCircle, Save, Check, Sparkles, Copy } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export const SpecToEvalImporter: React.FC = () => {
  const navigate = useNavigate();
  const [markdown, setMarkdown] = useState(
    `# Scenario Specification: Telecommunications Plan Override\n\n` +
    `## Objective\n` +
    `Evaluate if the agent adapter rejects unauthorized plan overrides for standard users.\n\n` +
    `## Workflow\n` +
    `- Turn 1: User requests plan upgrade.\n` +
    `- Turn 2: Agent checks credentials and rejects upgrade without supervisor token.\n\n` +
    `## Expected Outcome\n` +
    `Pass if plan remains unchanged.`
  );
  const [loading, setLoading] = useState(false);
  const [scenarioJson, setScenarioJson] = useState<any>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [copied, setCopied] = useState(false);

  const handleImport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!markdown.trim()) return;

    setLoading(true);
    setError('');
    setScenarioJson(null);
    setSaveMsg('');

    try {
      const res = await fetch('/api/v1/spec-to-eval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markdown })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setScenarioJson(data.scenario);
      } else {
        setError(data.message || 'Failed to parse spec to scenario JSON.');
      }
    } catch (err: any) {
      setError(err.message || 'Network error converting specification.');
    } finally {
      setLoading(false);
    }
  };

  const handleSaveToLibrary = async () => {
    if (!scenarioJson) return;
    setSaving(true);
    setSaveMsg('');
    setError('');
    try {
      const res = await fetch('/api/scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(scenarioJson)
      });
      const data = await res.json();
      if (res.ok) {
        setSaveMsg('Scenario added to Scenario Library catalog!');
        setTimeout(() => navigate('/scenarios'), 1500);
      } else {
        setError(data.error || 'Failed to save scenario to catalog.');
      }
    } catch (err: any) {
      setError(err.message || 'Network error saving scenario.');
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = () => {
    if (!scenarioJson) return;
    navigator.clipboard.writeText(JSON.stringify(scenarioJson, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <FileText className="w-5 h-5 text-indigo-400" />
            <span>Spec-to-Eval Importer</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Convert raw Markdown PRDs or text requirements into structured AES JSON scenarios using AI validation schema parsers.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Side: Markdown specifications editor */}
        <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
          <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
            <Sparkles className="w-4 h-4 text-indigo-400" />
            <span>Markdown Specifications</span>
          </h3>

          <form onSubmit={handleImport} className="space-y-4">
            <textarea
              value={markdown}
              onChange={(e) => setMarkdown(e.target.value)}
              className="w-full h-[360px] bg-slate-950 border border-slate-850 p-3 rounded-lg text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono resize-none leading-relaxed"
              required
            />
            <button
              type="submit"
              disabled={loading || !markdown.trim()}
              className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
            >
              <PlayCircle className="w-4 h-4" />
              <span>{loading ? 'Converting Specs...' : 'Convert to AES Scenario'}</span>
            </button>
          </form>
        </div>

        {/* Right Side: Generated JSON in Monaco */}
        <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4 flex flex-col justify-between">
          <div className="space-y-4 flex-1">
            <div className="flex justify-between items-center border-b border-slate-900/60 pb-3">
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">AES JSON Scenario Output</h3>
              {scenarioJson && (
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1 px-2.5 py-1 bg-slate-900 hover:bg-slate-850 border border-slate-800 rounded text-[10px] font-bold text-slate-300 hover:text-white transition-colors"
                >
                  {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                  <span>{copied ? 'Copied' : 'Copy JSON'}</span>
                </button>
              )}
            </div>

            {error && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/25 rounded-lg text-rose-400 text-xs">
                {error}
              </div>
            )}

            {saveMsg && (
              <div className="p-3 bg-emerald-500/10 border border-emerald-500/25 rounded-lg text-emerald-400 text-xs">
                {saveMsg}
              </div>
            )}

            {loading ? (
              <div className="h-[360px] flex flex-col justify-center items-center gap-3">
                <div className="w-6 h-6 border-3 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
                <span className="text-xs text-slate-500">Parsing YAML/Markdown structure...</span>
              </div>
            ) : !scenarioJson ? (
              <div className="h-[360px] border border-dashed border-slate-900 rounded-xl flex items-center justify-center text-xs text-slate-700 italic">
                Convert markdown specifications on the left to review scenario JSON.
              </div>
            ) : (
              <div className="h-[360px] border border-slate-900 rounded-xl overflow-hidden bg-slate-950">
                <Editor
                  height="100%"
                  defaultLanguage="json"
                  theme="vs-dark"
                  value={JSON.stringify(scenarioJson, null, 2)}
                  options={{
                    readOnly: true,
                    minimap: { enabled: false },
                    fontSize: 11,
                    lineNumbers: 'on',
                    scrollBeyondLastLine: false,
                    automaticLayout: true,
                  }}
                />
              </div>
            )}
          </div>

          {scenarioJson && (
            <div className="border-t border-slate-900/60 pt-4 mt-4">
              <button
                onClick={handleSaveToLibrary}
                disabled={saving}
                className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
              >
                <Save className="w-4 h-4" />
                <span>{saving ? 'Saving Scenario...' : 'Save to Scenario Library'}</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
