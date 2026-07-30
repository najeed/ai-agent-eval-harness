import React, { useState, useEffect } from 'react';
import { Search, AlertTriangle, ExternalLink, HelpCircle, FileText, ChevronLeft, ChevronRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { FailureCategoryBadge } from '../components/FailureCategoryBadge';

interface FailureMatch {
  timestamp: string;
  run_id: string;
  event: string;
  status: string;
  triage_tag: string;
  metric: string | null;
  content: string;
  task_id: string | null;
}

export const FailureCorpus: React.FC = () => {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<FailureMatch[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(0);
  const [mode, setMode] = useState<'text' | 'regex'>('text');
  const [error, setError] = useState('');
  const [savedQueries, setSavedQueries] = useState<string[]>(() => {
    const saved = localStorage.getItem('agentv-saved-searches');
    return saved ? JSON.parse(saved) : ['timeout', 'logic_state_stall', 'OOM', 'unauthorized'];
  });

  // Debounce query inputs to avoid spamming the backend
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query);
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  // Check if string looks like regex to update mode indicator reactively
  useEffect(() => {
    if (anyRegexChars(query)) {
      setMode('regex');
    } else {
      setMode('text');
    }
  }, [query]);

  const anyRegexChars = (str: string) => {
    return /[\.\+\*\?\^\$\(\)\[\]\{\}\|\\\/]/.test(str);
  };

  const fetchResults = async (searchPage = 1) => {
    if (!debouncedQuery.trim()) {
      setResults([]);
      setTotal(0);
      setPages(0);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await fetch(
        `/api/failures/search?q=${encodeURIComponent(debouncedQuery)}&page=${searchPage}&limit=12`
      );
      const json = await res.json();
      if (res.ok) {
        setResults(json.matches || []);
        setTotal(json.total || 0);
        setPages(json.pages || 0);
        setPage(json.page || 1);
        setMode(json.mode || 'text');
      } else {
        setError(json.error || 'Failed to search failure corpus.');
      }
    } catch (err: any) {
      setError(err.message || 'Network error querying Failure Corpus.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchResults(1);
  }, [debouncedQuery]);

  const handlePageChange = (newPage: number) => {
    if (newPage < 1 || newPage > pages) return;
    fetchResults(newPage);
  };

  const saveSearchQuery = () => {
    const trimmed = query.trim();
    if (!trimmed || savedQueries.includes(trimmed)) return;
    const updated = [...savedQueries, trimmed];
    setSavedQueries(updated);
    localStorage.setItem('agentv-saved-searches', JSON.stringify(updated));
  };

  const removeSavedQuery = (q: string) => {
    const updated = savedQueries.filter((item) => item !== q);
    setSavedQueries(updated);
    localStorage.setItem('agentv-saved-searches', JSON.stringify(updated));
  };

  // Helper to highlight matching text or regex pattern
  const highlightContent = (text: string, searchStr: string) => {
    if (!searchStr) return text;
    try {
      let regex: RegExp;
      if (anyRegexChars(searchStr)) {
        regex = new RegExp(`(${searchStr})`, 'gi');
      } else {
        const escaped = searchStr.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
        regex = new RegExp(`(${escaped})`, 'gi');
      }
      const parts = text.split(regex);
      return (
        <>
          {parts.map((part, i) =>
            regex.test(part) ? (
              <mark key={i} className="bg-yellow-500/20 text-yellow-200 border border-yellow-500/30 px-0.5 rounded font-bold font-mono">
                {part}
              </mark>
            ) : (
              part
            )
          )}
        </>
      );
    } catch (e) {
      return text;
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Search className="w-5 h-5 text-indigo-400" />
            <span>Failure Corpus Search</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Real-time regex indexing across all logged runs. Scan logs, stack traces, and environment mutation logs in the master database.
          </p>
        </div>
      </div>

      {/* Main Search Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left Side: Playbooks & Saved Queries */}
        <div className="space-y-4">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-4 space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">Failure Playbooks</h3>
              <span title="Click a tag to execute search">
                <HelpCircle className="w-3.5 h-3.5 text-slate-500" />
              </span>
            </div>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              Saved searches help trace recurring logic errors and sandboxed security breaches across active CI builds.
            </p>
            <div className="flex flex-wrap gap-1.5 pt-2">
              {savedQueries.map((q) => (
                <div
                  key={q}
                  className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-900 hover:bg-slate-850 border border-slate-800 rounded-lg text-slate-300 hover:text-white transition-colors cursor-pointer text-[10px] font-mono"
                  onClick={() => setQuery(q)}
                >
                  <span>{q}</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      removeSavedQuery(q);
                    }}
                    className="text-slate-600 hover:text-rose-400 font-bold ml-1 text-[8px]"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Side: Search & Results */}
        <div className="lg:col-span-3 space-y-4">
          {/* Search Input Box */}
          <div className="bg-slate-950/60 border border-slate-900 rounded-xl p-3 flex items-center gap-3">
            <Search className="w-5 h-5 text-slate-500 shrink-0" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by tag, message, regex (e.g. timeout.*500 or sandbox)..."
              className="flex-1 bg-transparent border-none text-slate-200 text-xs focus:outline-none placeholder-slate-600"
            />
            {/* Mode status indicator */}
            <div className="flex items-center gap-1.5 border-l border-slate-900 pl-3 select-none">
              <span className={`px-2 py-0.5 rounded text-[9px] font-bold font-mono tracking-wider transition-colors ${
                mode === 'regex' 
                  ? 'bg-purple-500/10 border border-purple-500/25 text-purple-400' 
                  : 'bg-indigo-500/10 border border-indigo-500/25 text-indigo-400'
              }`}>
                {mode.toUpperCase()}
              </span>
              {query && (
                <button
                  onClick={saveSearchQuery}
                  className="px-2 py-0.5 bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-400 hover:text-white text-[9px] font-bold rounded"
                >
                  Save
                </button>
              )}
            </div>
          </div>

          {error && (
            <div className="p-3.5 bg-rose-500/10 border border-rose-500/25 rounded-xl text-rose-400 text-xs flex gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* Results Area */}
          {loading ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3">
              <div className="w-7 h-7 border-3 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
              <span className="text-xs text-slate-500">Scanning failure corpus logs...</span>
            </div>
          ) : results.length === 0 ? (
            <div className="bg-slate-950/20 border border-slate-900 rounded-xl p-16 text-center text-slate-500">
              <FileText className="w-10 h-10 text-slate-800 mx-auto mb-3" />
              <h3 className="text-xs font-bold text-slate-400">
                {query ? 'No Failure Events Matched Query' : 'Type to search Failure Corpus'}
              </h3>
              <p className="text-[10px] text-slate-600 mt-1 max-w-sm mx-auto">
                {query 
                  ? 'Double check regex syntax or search keywords. Common tags include logic_state_stall, infra_timeout, or security.' 
                  : 'Execute regex strings directly on our index of historical failure traces.'}
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex justify-between items-center text-[10px] text-slate-500 font-mono">
                <span>FOUND {total} MATCHING FAILURES</span>
                <span>PAGE {page} OF {pages}</span>
              </div>

              {/* Cards Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {results.map((match, i) => (
                  <div
                    key={i}
                    className="bg-slate-950/30 border border-slate-900 rounded-xl p-4 hover:border-slate-800 transition-all flex flex-col justify-between gap-3 group"
                  >
                    <div className="space-y-2">
                      <div className="flex justify-between items-start gap-2">
                        <div className="flex flex-wrap gap-1.5 items-center">
                          {match.triage_tag && (
                            <FailureCategoryBadge category={match.triage_tag} />
                          )}
                          <span className="text-[9px] bg-slate-900 text-slate-400 font-mono px-1.5 py-0.5 rounded">
                            {match.event}
                          </span>
                        </div>
                        <span className="text-[9px] text-slate-600 font-mono shrink-0">
                          {match.timestamp ? new Date(match.timestamp).toLocaleTimeString() : 'N/A'}
                        </span>
                      </div>

                      {/* Content Snippet */}
                      <p className="text-[11px] text-slate-300 font-mono leading-relaxed bg-slate-950/50 p-2.5 rounded border border-slate-900/50 overflow-x-auto whitespace-pre-wrap break-all max-h-32">
                        {highlightContent(match.content, debouncedQuery)}
                      </p>
                    </div>

                    <div className="flex items-center justify-between border-t border-slate-900/50 pt-2.5 mt-1">
                      <div className="flex flex-col min-w-0">
                        <span className="text-[8px] uppercase tracking-wider text-slate-500 font-bold">Run ID Reference</span>
                        <span className="text-[10px] text-slate-400 font-semibold truncate max-w-[140px] font-mono">
                          {match.run_id}
                        </span>
                      </div>
                      <button
                        onClick={() => navigate(`/debugger?run_id=${match.run_id}`)}
                        className="flex items-center gap-1 text-[10px] text-indigo-400 hover:text-indigo-300 font-bold transition-colors"
                      >
                        <span>Investigate Trace</span>
                        <ExternalLink className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              {/* Pagination Controls */}
              {pages > 1 && (
                <div className="flex items-center justify-center gap-2 pt-4">
                  <button
                    disabled={page === 1}
                    onClick={() => handlePageChange(page - 1)}
                    className="p-1.5 bg-slate-900 border border-slate-800 disabled:opacity-30 text-slate-400 hover:text-white rounded transition-colors"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="text-[10px] font-mono text-slate-500">
                    PAGE {page} OF {pages}
                  </span>
                  <button
                    disabled={page === pages}
                    onClick={() => handlePageChange(page + 1)}
                    className="p-1.5 bg-slate-900 border border-slate-800 disabled:opacity-30 text-slate-400 hover:text-white rounded transition-colors"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
