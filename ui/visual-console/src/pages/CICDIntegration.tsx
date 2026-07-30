import React, { useState } from 'react';
import Editor from '@monaco-editor/react';
import { Copy, Download, Check, Sparkles, FileText } from 'lucide-react';

export const CICDIntegration: React.FC = () => {
  const [generating, setGenerating] = useState(false);
  const [yamlContent, setYamlContent] = useState('');
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [downloaded, setDownloaded] = useState(false);

  const handleGenerateWorkflow = async () => {
    setGenerating(true);
    setError('');
    setYamlContent('');
    try {
      const res = await fetch('/api/ci/generate', {
        method: 'POST',
      });
      const data = await res.json();
      if (res.ok && data.yaml) {
        setYamlContent(data.yaml);
      } else {
        setError(data.error || 'Failed to generate workflow file.');
      }
    } catch (err: any) {
      setError(err.message || 'Network error triggering scaffold CI generator.');
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = () => {
    if (!yamlContent) return;
    navigator.clipboard.writeText(yamlContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!yamlContent) return;
    const blob = new Blob([yamlContent], { type: 'text/yaml' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'eval_harness_ci.yml';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setDownloaded(true);
    setTimeout(() => setDownloaded(false), 2000);
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <FileText className="w-5 h-5 text-indigo-400" />
            <span>CI/CD Integration</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Automate AI agent evaluation gating in continuous integration pipelines. Generate GitHub Actions to certify builds on PR triggers.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Side: CI Setup Description & Controls */}
        <div className="space-y-6 lg:col-span-1">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <span>CI Pipeline Gating</span>
            </h3>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Gating agent pull requests is critical to prevent code drift and regression issues. The generated configuration script performs three main security locks:
            </p>
            <ul className="space-y-2.5 text-[11px] text-slate-500 list-disc pl-4 leading-relaxed">
              <li>Configures a clean virtual test runner environment on PR push hooks.</li>
              <li>Runs the agent verification suites locally to compile pass rate statistics.</li>
              <li>Validates task scores against objective threshold limits before merges are unlocked.</li>
            </ul>

            <button
              onClick={handleGenerateWorkflow}
              disabled={generating}
              className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-2"
            >
              {generating ? 'Generating configuration...' : 'Generate CI Workflow (.yml)'}
            </button>
          </div>

          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-3">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider">Scaffold Details</h3>
            <div className="space-y-2 text-[10px] font-mono text-slate-500">
              <div className="flex justify-between border-b border-slate-900/60 pb-1.5">
                <span>Output Directory</span>
                <span className="text-slate-400">.github/workflows/</span>
              </div>
              <div className="flex justify-between border-b border-slate-900/60 pb-1.5">
                <span>Recommended Version</span>
                <span className="text-slate-400">python-version: '3.10'</span>
              </div>
              <div className="flex justify-between">
                <span>Command Execution</span>
                <span className="text-slate-450">agentv evaluate</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right Side: Monaco Code Editor Viewer */}
        <div className="lg:col-span-2 bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
          <div className="flex justify-between items-center border-b border-slate-900/60 pb-3">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider">eval_harness_ci.yml</h3>
            {yamlContent && (
              <div className="flex gap-2">
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-900 hover:bg-slate-850 border border-slate-800 rounded text-[10px] font-bold text-slate-300 hover:text-white transition-colors"
                >
                  {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                  <span>{copied ? 'Copied' : 'Copy'}</span>
                </button>
                <button
                  onClick={handleDownload}
                  className="flex items-center gap-1.5 px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-[10px] font-bold transition-colors"
                >
                  {downloaded ? <Check className="w-3 h-3 text-emerald-400" /> : <Download className="w-3 h-3" />}
                  <span>{downloaded ? 'Downloaded' : 'Download'}</span>
                </button>
              </div>
            )}
          </div>

          {error && (
            <div className="p-4 bg-rose-500/10 border border-rose-500/25 rounded-xl text-rose-400 text-xs">
              {error}
            </div>
          )}

          {!yamlContent && !generating ? (
            <div className="h-[360px] border border-dashed border-slate-900 rounded-xl flex flex-col justify-center items-center text-slate-500 text-center p-10">
              <FileText className="w-10 h-10 text-slate-800 mb-3" />
              <h4 className="text-xs font-bold text-slate-400">CI Config Viewer</h4>
              <p className="text-[10px] text-slate-600 mt-1 max-w-xs leading-relaxed">
                Click generate in the left panel to trigger scaffold creation and load code highlights in the Monaco Editor.
              </p>
            </div>
          ) : generating ? (
            <div className="h-[360px] flex flex-col justify-center items-center gap-3">
              <div className="w-6 h-6 border-3 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
              <span className="text-xs text-slate-500">Compiling YAML structures...</span>
            </div>
          ) : (
            <div className="h-[360px] border border-slate-900 rounded-xl overflow-hidden bg-slate-950">
              <Editor
                height="100%"
                defaultLanguage="yaml"
                theme="vs-dark"
                value={yamlContent}
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
      </div>
    </div>
  );
};
