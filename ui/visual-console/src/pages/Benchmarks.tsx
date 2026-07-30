import React, { useState } from 'react';
import { Cpu, PlayCircle, Sparkles, Activity, Info } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

export const Benchmarks: React.FC = () => {
  const [running, setRunning] = useState(false);
  const [activeSuite, setActiveSuite] = useState<'gaia' | 'assistantbench'>('gaia');
  const [scores, setScores] = useState<any | null>(null);

  const handleRunBenchmark = () => {
    setRunning(true);
    setScores(null);
    // Simulate benchmark execution progress and metrics
    setTimeout(() => {
      setRunning(false);
      if (activeSuite === 'gaia') {
        setScores({
          total_tasks: 120,
          pass_rate: 42.5,
          by_level: { level_1: 58.2, level_2: 36.4, level_3: 15.6 },
          status: 'success'
        });
      } else {
        setScores({
          total_tasks: 80,
          pass_rate: 56.3,
          by_level: { search: 72.1, planning: 48.4, execution: 35.8 },
          status: 'success'
        });
      }
    }, 1500);
  };

  const chartData = scores ? (
    activeSuite === 'gaia' ? [
      { name: 'Level 1', Score: scores.by_level.level_1 },
      { name: 'Level 2', Score: scores.by_level.level_2 },
      { name: 'Level 3', Score: scores.by_level.level_3 },
    ] : [
      { name: 'Search', Score: scores.by_level.search },
      { name: 'Planning', Score: scores.by_level.planning },
      { name: 'Execution', Score: scores.by_level.execution },
    ]
  ) : [];

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Cpu className="w-5 h-5 text-indigo-400" />
            <span>Industry Benchmarks</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Integrate and execute third-party agent evaluations including GAIA and AssistantBench. Track standardized benchmark capability scores.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Side: Benchmark selection panel */}
        <div className="space-y-6 lg:col-span-1">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <span>Select Suite</span>
            </h3>

            <div className="space-y-2">
              <button
                onClick={() => {
                  setActiveSuite('gaia');
                  setScores(null);
                }}
                className={`w-full flex items-center justify-between p-3 rounded-lg border text-left transition-all ${
                  activeSuite === 'gaia'
                    ? 'bg-indigo-500/5 border-indigo-500/20 text-indigo-300 font-bold'
                    : 'bg-slate-950/40 border-slate-850 text-slate-400 hover:bg-slate-900/50'
                }`}
              >
                <div>
                  <h4 className="text-xs text-slate-200 font-bold">GAIA Benchmark</h4>
                  <p className="text-[9px] text-slate-500 mt-0.5">General AI Assistants evaluation set</p>
                </div>
                <span className="px-1.5 py-0.5 bg-slate-900 text-slate-550 border border-slate-800 rounded text-[8px] font-extrabold uppercase font-mono tracking-wider shrink-0">
                  Sample Task
                </span>
              </button>

              <button
                onClick={() => {
                  setActiveSuite('assistantbench');
                  setScores(null);
                }}
                className={`w-full flex items-center justify-between p-3 rounded-lg border text-left transition-all ${
                  activeSuite === 'assistantbench'
                    ? 'bg-indigo-500/5 border-indigo-500/20 text-indigo-300 font-bold'
                    : 'bg-slate-950/40 border-slate-850 text-slate-400 hover:bg-slate-900/50'
                }`}
              >
                <div>
                  <h4 className="text-xs text-slate-200 font-bold">AssistantBench</h4>
                  <p className="text-[9px] text-slate-500 mt-0.5">Web navigation and tool planning tasks</p>
                </div>
                <span className="px-1.5 py-0.5 bg-slate-900 text-slate-550 border border-slate-800 rounded text-[8px] font-extrabold uppercase font-mono tracking-wider shrink-0">
                  Sample Task
                </span>
              </button>
            </div>

            <button
              onClick={handleRunBenchmark}
              disabled={running}
              className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
            >
              <PlayCircle className="w-4 h-4" />
              <span>{running ? 'Executing Benchmark...' : 'Run Evaluator (Simulation)'}</span>
            </button>
          </div>

          <div className="p-4 bg-indigo-500/5 border border-indigo-500/10 rounded-xl flex items-start gap-2.5">
            <Info className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
            <p className="text-[10px] text-slate-500 leading-relaxed leading-normal">
              * Backend Note: Core benchmark runners return sample data templates for local demonstration. Live third-party dataset ingestion is bypassed for trust stability.
            </p>
          </div>
        </div>

        {/* Right Side: Benchmark execution output charts */}
        <div className="lg:col-span-2 space-y-4">
          {!scores && !running ? (
            <div className="bg-slate-950/15 border border-slate-900 border-dashed rounded-xl p-24 text-center text-slate-500 h-full flex flex-col justify-center">
              <Activity className="w-12 h-12 text-slate-800 mx-auto mb-4" />
              <h3 className="text-xs font-bold text-slate-400">Benchmark Console Awaiting Launch</h3>
              <p className="text-[10px] text-slate-600 mt-1 max-w-sm mx-auto leading-relaxed">
                Click Run Evaluator on the left to trigger the benchmark simulation. The results will outline pass rate curves, total tasks resolved, and drill-down metrics.
              </p>
            </div>
          ) : running ? (
            <div className="h-96 flex flex-col justify-center items-center gap-3 bg-slate-950/10 border border-slate-900 rounded-xl">
              <div className="w-8 h-8 border-4 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
              <span className="text-xs text-slate-500">Injecting datasets and validating agents...</span>
            </div>
          ) : (
            <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4 animate-slide-in">
              <div className="flex justify-between items-center border-b border-slate-900/60 pb-3">
                <h3 className="text-xs font-bold text-white uppercase tracking-wider capitalize">
                  {activeSuite} Yield Metrics
                </h3>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="bg-slate-950/80 border border-slate-850 p-4 rounded-xl text-center">
                  <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Overall Pass Rate</span>
                  <div className="text-3xl font-extrabold text-indigo-400 mt-1 font-mono">{scores.pass_rate}%</div>
                </div>
                <div className="bg-slate-950/80 border border-slate-850 p-4 rounded-xl text-center">
                  <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Tasks Evaluated</span>
                  <div className="text-3xl font-extrabold text-white mt-1 font-mono">{scores.total_tasks}</div>
                </div>
              </div>

              <div className="h-60 w-full pt-4">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" opacity={0.3} />
                    <XAxis dataKey="name" stroke="#475569" fontSize={9} />
                    <YAxis stroke="#475569" fontSize={9} />
                    <Tooltip contentStyle={{ backgroundColor: '#020617', borderColor: '#1e293b', fontSize: '10px' }} />
                    <Bar dataKey="Score" fill="#6366f1" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
