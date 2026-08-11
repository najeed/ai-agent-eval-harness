import React, { useState, useEffect } from 'react';
import { Play, Download, ExternalLink, FileText, CheckCircle2, AlertTriangle } from 'lucide-react';

interface JobStatus {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  progress: string;
  params: {
    mode: string;
    path: string;
    agent_name: string;
    protocol: string;
    agent: string;
    parallel: number;
  };
  results?: {
    batch_id: string;
    manifest: any;
    zip_file: string | null;
    leaderboard_html: string | null;
  };
  logs?: string;
  error?: string;
}

export const PublicationSuite: React.FC = () => {
  // Form inputs
  const [mode, setMode] = useState<'pilot' | 'standard'>('standard');
  const [path, setPath] = useState('scenarios/');
  const [agentName, setAgentName] = useState('Verified-Adapter-v1');
  const [protocol, setProtocol] = useState('http');
  const [agent, setAgent] = useState('http://localhost:5001/execute_task');
  const [parallel, setParallel] = useState(4);

  // Active Job states
  const [activeJobId, setActiveJobId] = useState<string | null>(() => {
    return localStorage.getItem('agentv-active-pub-job') || null;
  });
  const [job, setJob] = useState<JobStatus | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState('');

  // cancelRef is the authoritative polling stop flag.
  // It is set to true when: abort is clicked, job reaches terminal state, or component unmounts.
  // We deliberately do NOT set activeJobId=null on terminal states — that would collapse
  // the monitor panel before the user can read results.
  const cancelRef = React.useRef(false);

  useEffect(() => {
    if (!activeJobId) {
      setJob(null);
      return;
    }

    // Reset cancel flag for the new job
    cancelRef.current = false;
    let timerId: any = null;

    const poll = async () => {
      if (cancelRef.current) return;
      try {
        const res = await fetch(`/api/publish/${activeJobId}`);
        if (cancelRef.current) return; // Abort fired while request was in-flight
        if (res.status === 404) {
          // Job evicted from server — mark cancelled, leave UI intact so user sees result
          cancelRef.current = true;
          return;
        }
        if (!res.ok) {
          throw new Error(`HTTP status ${res.status}`);
        }
        const data = (await res.json()) as JobStatus;
        if (cancelRef.current) return;
        setJob(data);
        if (data.status === 'completed' || data.status === 'failed') {
          // Stop polling but keep activeJobId set — panel stays visible
          cancelRef.current = true;
          localStorage.removeItem('agentv-active-pub-job');
          return;
        }
      } catch (e) {
        console.error('Error polling publish job:', e);
      }

      if (!cancelRef.current) {
        timerId = setTimeout(poll, 2000);
      }
    };

    poll();

    return () => {
      cancelRef.current = true;
      if (timerId) clearTimeout(timerId);
    };
  }, [activeJobId]);

  const handleStartRun = async (e: React.FormEvent) => {
    e.preventDefault();
    setTriggering(true);
    setTriggerError('');
    setJob(null);
    try {
      const res = await fetch('/api/publish', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode,
          path,
          agent_name: agentName,
          protocol,
          agent,
          parallel
        })
      });
      const data = await res.json();
      if (res.ok && data.job_id) {
        setActiveJobId(data.job_id);
        localStorage.setItem('agentv-active-pub-job', data.job_id);
      } else {
        setTriggerError(data.error || 'Failed to trigger publication conductor run.');
        if (data.active_job_id) {
          // Bind the running job so the user is immediately shown the active job monitor and can stop it
          setActiveJobId(data.active_job_id);
          localStorage.setItem('agentv-active-pub-job', data.active_job_id);
        }
      }
    } catch (err: any) {
      setTriggerError(err.message || 'Network error triggering conductor.');
    } finally {
      setTriggering(false);
    }
  };

  const handleClearActiveJob = () => {
    setActiveJobId(null);
    setJob(null);
    localStorage.removeItem('agentv-active-pub-job');
  };

  const handleStopRun = async () => {
    if (!activeJobId) return;
    const jobToStop = activeJobId;
    // Cancel polling via ref — does NOT collapse the monitor panel.
    // User can still read the job state. Panel only resets when they start a new run.
    cancelRef.current = true;
    localStorage.removeItem('agentv-active-pub-job');
    setJob(prev => prev ? {
      ...prev,
      status: 'failed',
      progress: 'Job stopped.',
      error: 'Job aborted by user request.'
    } : null);
    try {
      await fetch(`/api/publish/${jobToStop}/stop`, { method: 'POST' });
    } catch (e) {
      console.error('Error stopping publish job:', e);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <FileText className="w-5 h-5 text-indigo-400" />
            <span>Publication Suite</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Orchestrate zero-touch statistical batches and signed zip packages for compliance audits and third-party validation tests.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Side: Launch Console Form */}
        <div className="space-y-6 lg:col-span-1">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Play className="w-4 h-4 text-indigo-400" />
              <span>Conductor Console</span>
            </h3>

            {activeJobId ? (
              <div className="space-y-3 pt-2">
                <div className="p-3 bg-indigo-500/5 border border-indigo-500/20 rounded-lg space-y-1.5">
                  <span className="text-[9px] text-indigo-400 font-bold uppercase tracking-wider font-mono block">Active Job ID</span>
                  <p className="text-slate-200 font-mono font-bold text-xs truncate">{activeJobId}</p>
                </div>
                <button
                  onClick={handleClearActiveJob}
                  className="w-full py-2 bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-400 hover:text-white text-xs font-bold rounded-lg transition-colors"
                >
                  Configure New Run
                </button>
              </div>
            ) : (
              <form onSubmit={handleStartRun} className="space-y-4">
                {/* Mode Select */}
                <div className="space-y-1.5">
                  <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Evaluation Mode</label>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => setMode('standard')}
                      className={`py-1.5 rounded text-xs font-bold transition-all border ${mode === 'standard'
                          ? 'bg-indigo-600 border-indigo-500 text-white'
                          : 'bg-slate-950 border-slate-850 text-slate-400 hover:text-slate-350'
                        }`}
                    >
                      Standard Batch
                    </button>
                    <button
                      type="button"
                      onClick={() => setMode('pilot')}
                      className={`py-1.5 rounded text-xs font-bold transition-all border ${mode === 'pilot'
                          ? 'bg-indigo-600 border-indigo-500 text-white'
                          : 'bg-slate-950 border-slate-850 text-slate-400 hover:text-slate-350'
                        }`}
                    >
                      Pilot Preview
                    </button>
                  </div>
                </div>

                {/* Scenario Dir */}
                <div className="space-y-1">
                  <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Scenario Path</label>
                  <input
                    type="text"
                    value={path}
                    onChange={(e) => setPath(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>

                {/* Adapter Name */}
                <div className="space-y-1">
                  <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Adapter Identity</label>
                  <input
                    type="text"
                    value={agentName}
                    onChange={(e) => setAgentName(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                {/* Protocol */}
                <div className="space-y-1">
                  <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Connection Protocol</label>
                  <select
                    value={protocol}
                    onChange={(e) => setProtocol(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-350 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="http">http (Standard JSON-RPC)</option>
                    <option value="otel">otel (OpenTelemetry)</option>
                  </select>
                </div>

                {/* Agent URL */}
                <div className="space-y-1">
                  <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Adapter Endpoint URL</label>
                  <input
                    type="text"
                    value={agent}
                    onChange={(e) => setAgent(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>

                {/* Parallel Workers */}
                <div className="space-y-1.5">
                  <div className="flex justify-between items-center text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                    <span>Parallel Workers</span>
                    <span className="text-indigo-400 font-mono">{parallel} threads</span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="16"
                    value={parallel}
                    onChange={(e) => setParallel(parseInt(e.target.value))}
                    className="w-full h-1 bg-slate-850 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                  />
                </div>

                {triggerError && (
                  <div className="p-3 bg-rose-500/10 border border-rose-500/25 rounded text-rose-400 text-[10px]">
                    {triggerError}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={triggering || !agentName.trim()}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors"
                >
                  {triggering ? 'Launching Conductor...' : 'Launch Batch Conductor'}
                </button>
              </form>
            )}
          </div>
        </div>

        {/* Right Side: Active Job Monitor or Welcome Screen */}
        <div className="lg:col-span-2 space-y-4">
          {!activeJobId ? (
            <div className="bg-slate-950/15 border border-slate-900 border-dashed rounded-xl p-24 text-center text-slate-500 h-full flex flex-col justify-center">
              <FileText className="w-12 h-12 text-slate-800 mx-auto mb-4" />
              <h3 className="text-xs font-bold text-slate-400">Publication Monitor Awaiting Job</h3>
              <p className="text-[10px] text-slate-600 mt-1 max-w-sm mx-auto leading-relaxed">
                Configure your adapter parameters on the left and launch a run. The Conductor will orchestrate serial or parallel runs, compute statistics, generate lead HTML, and sign a zip bundle.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Job Status Banner */}
              <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
                <div className="flex justify-between items-center border-b border-slate-900/60 pb-3">
                  <div className="space-y-0.5">
                    <span className="text-[8px] uppercase tracking-wider text-slate-500 font-bold">Monitor Status</span>
                    <h3 className="text-xs font-bold text-slate-200 uppercase font-mono">{job?.status || 'Queued'}</h3>
                  </div>
                  <span className={`px-2.5 py-1 rounded text-[9px] font-bold uppercase tracking-wider border ${job?.status === 'completed' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' :
                      job?.status === 'failed' ? 'bg-rose-500/10 border-rose-500/20 text-rose-400' :
                        'bg-amber-500/10 border-amber-500/20 text-amber-400 animate-pulse'
                    }`}>
                    {job?.status || 'Pending'}
                  </span>
                </div>

                <div className="flex justify-between items-center">
                  <div className="space-y-1">
                    <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">Active Phase</span>
                    <p className="text-xs font-bold text-white leading-relaxed italic">{job?.progress}</p>
                  </div>
                  {(job?.status === 'running' || job?.status === 'queued') && (
                    <button
                      onClick={handleStopRun}
                      className="px-3 py-1.5 bg-rose-950 border border-rose-900/60 hover:bg-rose-900 hover:text-white text-rose-400 text-[10px] font-bold rounded transition-colors"
                    >
                      Abort Run
                    </button>
                  )}
                </div>

                {job?.status === 'failed' && job.error && (
                  <div className="p-3 bg-rose-500/10 border border-rose-500/25 rounded-lg text-rose-400 text-xs">
                    <div className="font-bold flex items-center gap-1.5 mb-1">
                      <AlertTriangle className="w-4 h-4 shrink-0" />
                      <span>Conductor Error Encountered</span>
                    </div>
                    <p className="font-mono text-[10px] leading-relaxed bg-slate-950 p-2 rounded">{job.error}</p>
                  </div>
                )}
              </div>

              {/* Complete Job Deliverables */}
              {job?.status === 'completed' && job.results && (
                <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
                  <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    <span>Conductor Deliverables Completed</span>
                  </h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {/* HTML Leaderboard link */}
                    {job.results.leaderboard_html && (
                      <a
                        href={`/v2/results/${job.results.batch_id}/${mode === 'pilot' ? 'pilot_preview.html' : 'leaderboard.html'}`}
                        target="_blank"
                        rel="noreferrer"
                        className="p-4 bg-indigo-500/5 hover:bg-indigo-500/10 border border-indigo-500/20 rounded-xl space-y-1.5 block group transition-all"
                      >
                        <div className="flex justify-between items-center">
                          <span className="text-[10px] text-indigo-400 font-bold uppercase tracking-wider">Phase 3 Result</span>
                          <ExternalLink className="w-3.5 h-3.5 text-slate-500 group-hover:text-indigo-400 transition-colors" />
                        </div>
                        <h4 className="text-xs font-bold text-white">View HTML Leaderboard</h4>
                        <p className="text-[10px] text-slate-500 leading-relaxed">Interactive chart.js metrics summary for browser display.</p>
                      </a>
                    )}

                    {/* Signed ZIP bundle */}
                    {job.results.zip_file && (
                      <a
                        href={`/api/publish/${job.job_id}/bundle`}
                        className="p-4 bg-emerald-500/5 hover:bg-emerald-500/10 border border-emerald-500/20 rounded-xl space-y-1.5 block group transition-all"
                      >
                        <div className="flex justify-between items-center">
                          <span className="text-[10px] text-emerald-400 font-bold uppercase tracking-wider">Phase 4 Result</span>
                          <Download className="w-3.5 h-3.5 text-slate-500 group-hover:text-emerald-400 transition-colors" />
                        </div>
                        <h4 className="text-xs font-bold text-white">Download ZIP Bundle</h4>
                        <p className="text-[10px] text-slate-500 leading-relaxed">Cryptographically signed ZIP export including audit manifest proof.</p>
                      </a>
                    )}
                  </div>
                </div>
              )}

              {/* Real-time Stdout Logging Panel */}
              <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-3">
                <h3 className="text-xs font-bold text-white uppercase tracking-wider">Job Execution logs</h3>
                <div className="w-full h-80 bg-slate-950 border border-slate-850 rounded-lg p-3 overflow-y-auto font-mono text-[10px] text-slate-350 space-y-1 select-text leading-relaxed">
                  {job?.logs ? (
                    job.logs.split('\n').map((line, i) => (
                      <div key={i} className="truncate">
                        {line}
                      </div>
                    ))
                  ) : (
                    <div className="text-slate-600 italic">Logs stream will load upon conductor initiation...</div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
