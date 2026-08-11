import React, { useState, useRef } from 'react';
import Editor from '@monaco-editor/react';
import { FileText, PlayCircle, Edit3, Check, Sparkles, Copy, UploadCloud } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export const SpecToEvalImporter: React.FC = () => {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
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
  const [copied, setCopied] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);

  const handleImport = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!markdown.trim()) return;

    setLoading(true);
    setError('');
    setScenarioJson(null);

    try {
      const res = await fetch('/api/v1/spec-to-eval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markdown })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setScenarioJson(data.scenario);
        window.dispatchEvent(new CustomEvent('agentv-toast', {
          detail: { message: 'Specification parsed successfully!', type: 'success' }
        }));
      } else {
        setError(data.message || 'Failed to parse spec to scenario JSON.');
      }
    } catch (err: any) {
      setError(err.message || 'Network error converting specification.');
    } finally {
      setLoading(false);
    }
  };

  const handleEditInComposer = () => {
    if (!scenarioJson) return;
    // Set in localStorage to be consumed by ScenarioComposer
    localStorage.setItem('aes-draft', JSON.stringify(scenarioJson));
    navigate('/editor');
  };

  const handleCopy = () => {
    if (!scenarioJson) return;
    navigator.clipboard.writeText(JSON.stringify(scenarioJson, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Drag and Drop files handlers
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleFile(files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFile(files[0]);
    }
  };

  const handleFile = (file: File) => {
    if (!file.name.endsWith('.md') && !file.name.endsWith('.txt')) {
      setError('Invalid file type. Only Markdown (.md) or text files are supported.');
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      if (text) {
        setMarkdown(text);
        setError('');
        window.dispatchEvent(new CustomEvent('agentv-toast', {
          detail: { message: `Loaded file: ${file.name}`, type: 'info' }
        }));
      }
    };
    reader.readAsText(file);
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
            Upload raw Markdown specifications or copy requirements text. AI validation parsers will automatically build structured evaluation workflows.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Side: Markdown Specifications input */}
        <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4 flex flex-col justify-between">
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                <Sparkles className="w-4 h-4 text-indigo-400" />
                <span>Specification Requirements</span>
              </h3>
              
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-900 hover:bg-slate-850 border border-slate-800 rounded text-[10px] font-bold text-slate-400 hover:text-slate-200 transition-all"
              >
                <UploadCloud className="w-3.5 h-3.5" />
                <span>Upload .md file</span>
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".md,.txt"
                onChange={handleFileChange}
                className="hidden"
              />
            </div>

            {/* Drag & Drop File Zone */}
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={`border border-dashed rounded-xl p-4 transition-all flex flex-col items-center justify-center text-center ${
                isDragOver
                  ? 'border-indigo-500 bg-indigo-500/5'
                  : 'border-slate-850 bg-slate-950/60 hover:border-slate-800'
              }`}
            >
              <textarea
                value={markdown}
                onChange={(e) => setMarkdown(e.target.value)}
                placeholder="Paste your markdown specification requirement document here, or drag and drop a markdown file..."
                className="w-full h-[280px] bg-transparent border-0 resize-none text-xs text-slate-200 focus:outline-none font-mono leading-relaxed"
                required
              />
              <span className="text-[9px] text-slate-650 mt-1 font-mono">
                Drag-and-drop a markdown document directly into the editor to load.
              </span>
            </div>
          </div>

          <button
            onClick={() => handleImport()}
            disabled={loading || !markdown.trim()}
            className="w-full py-2 mt-4 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
          >
            <PlayCircle className="w-4 h-4" />
            <span>{loading ? 'Converting Specs...' : 'Convert to AES Scenario'}</span>
          </button>
        </div>

        {/* Right Side: Generated JSON in Monaco */}
        <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4 flex flex-col justify-between">
          <div className="space-y-4 flex-1">
            <div className="flex justify-between items-center border-b border-slate-900/60 pb-3">
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">Draft AES JSON Scenario</h3>
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

            {loading ? (
              <div className="h-[360px] flex flex-col justify-center items-center gap-3">
                <div className="w-6 h-6 border-2 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
                <span className="text-xs text-slate-500">Executing parser schemas...</span>
              </div>
            ) : !scenarioJson ? (
              <div className="h-[360px] border border-dashed border-slate-900 rounded-xl flex items-center justify-center text-xs text-slate-700 italic">
                Awaiting specification conversion input.
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
                onClick={handleEditInComposer}
                className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
              >
                <Edit3 className="w-4 h-4" />
                <span>Edit in Scenario Composer (Unsaved Draft)</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
