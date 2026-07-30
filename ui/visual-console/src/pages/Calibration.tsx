import React, { useState } from 'react';
import { Sliders, Sparkles, RefreshCw, Info } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

export const Calibration: React.FC = () => {
  // Calibration Slider States
  const [flakiness, setFlakiness] = useState(15); // flakiness tolerance (percentage)
  const [timeout, setTimeoutVal] = useState(30); // timeout limit (seconds)
  const [temp, setTemp] = useState(0.2); // LLM Temperature
  const [maxTurns, setMaxTurns] = useState(10); // Max execution steps

  // Calculate simulated pass rate curve based on parameters
  // Higher maxTurns/timeout and lower flakiness/temp yields higher pass rate
  const getSimulatedPassRate = (fl: number, to: number, tp: number, mt: number) => {
    const base = 85;
    const flPenalty = fl * 0.4;
    const toBonus = Math.min(15, (to - 10) * 0.5);
    const tpPenalty = tp * 20;
    const mtBonus = Math.min(10, (mt - 5) * 0.8);
    return Math.max(10, Math.min(100, Math.round(base - flPenalty + toBonus - tpPenalty + mtBonus)));
  };

  const currentPassRate = getSimulatedPassRate(flakiness, timeout, temp, maxTurns);

  // Generate Recharts simulated historical trends based on configuration
  const chartData = [
    { name: 'Build 1', PassRate: getSimulatedPassRate(flakiness + 5, timeout - 5, temp + 0.1, maxTurns - 2) },
    { name: 'Build 2', PassRate: getSimulatedPassRate(flakiness + 2, timeout - 2, temp + 0.05, maxTurns - 1) },
    { name: 'Build 3', PassRate: getSimulatedPassRate(flakiness, timeout, temp, maxTurns) },
    { name: 'Build 4', PassRate: Math.min(100, getSimulatedPassRate(flakiness - 3, timeout + 5, temp - 0.05, maxTurns + 2)) },
    { name: 'Build 5', PassRate: Math.min(100, getSimulatedPassRate(flakiness - 5, timeout + 10, temp - 0.1, maxTurns + 4)) },
  ];

  const handleReset = () => {
    setFlakiness(15);
    setTimeoutVal(30);
    setTemp(0.2);
    setMaxTurns(10);
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Sliders className="w-5 h-5 text-indigo-400" />
            <span>Calibration Console</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Simulate scenario parameters and environment flakiness tolerances to model hypothetical pass rate curves across CI/CD execution runs.
          </p>
        </div>
        <button
          onClick={handleReset}
          className="p-2 bg-slate-950 border border-slate-900 rounded-lg text-slate-400 hover:text-slate-200 transition-colors"
          title="Reset Parameters"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Side: Parameters Slider Panel */}
        <div className="space-y-6 lg:col-span-1">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <span>Simulation Controls</span>
            </h3>

            {/* Flakiness */}
            <div className="space-y-2">
              <div className="flex justify-between items-center text-[10px] text-slate-500 font-bold uppercase">
                <span>Flakiness Tolerance</span>
                <span className="text-indigo-400 font-mono">{flakiness}% loss</span>
              </div>
              <input
                type="range"
                min="0"
                max="50"
                value={flakiness}
                onChange={(e) => setFlakiness(parseInt(e.target.value))}
                className="w-full h-1 bg-slate-850 rounded-lg appearance-none cursor-pointer accent-indigo-500"
              />
            </div>

            {/* Timeout */}
            <div className="space-y-2">
              <div className="flex justify-between items-center text-[10px] text-slate-500 font-bold uppercase">
                <span>Response Timeout</span>
                <span className="text-indigo-400 font-mono">{timeout}s limit</span>
              </div>
              <input
                type="range"
                min="5"
                max="120"
                value={timeout}
                onChange={(e) => setTimeoutVal(parseInt(e.target.value))}
                className="w-full h-1 bg-slate-850 rounded-lg appearance-none cursor-pointer accent-indigo-500"
              />
            </div>

            {/* LLM Temp */}
            <div className="space-y-2">
              <div className="flex justify-between items-center text-[10px] text-slate-500 font-bold uppercase">
                <span>LLM Temperature</span>
                <span className="text-indigo-400 font-mono">{temp.toFixed(2)} temp</span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={temp}
                onChange={(e) => setTemp(parseFloat(e.target.value))}
                className="w-full h-1 bg-slate-850 rounded-lg appearance-none cursor-pointer accent-indigo-500"
              />
            </div>

            {/* Max Steps */}
            <div className="space-y-2">
              <div className="flex justify-between items-center text-[10px] text-slate-500 font-bold uppercase">
                <span>Max Turn Threshold</span>
                <span className="text-indigo-400 font-mono">{maxTurns} max steps</span>
              </div>
              <input
                type="range"
                min="3"
                max="30"
                value={maxTurns}
                onChange={(e) => setMaxTurns(parseInt(e.target.value))}
                className="w-full h-1 bg-slate-850 rounded-lg appearance-none cursor-pointer accent-indigo-500"
              />
            </div>
          </div>

          <div className="p-4 bg-indigo-500/5 border border-indigo-500/10 rounded-xl flex items-start gap-2.5">
            <Info className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
            <p className="text-[10px] text-slate-500 leading-relaxed leading-normal">
              Parameter calibration models hypothetical target tolerances. Optimize values locally to establish scenario baseline floor profiles before promotional deployments.
            </p>
          </div>
        </div>

        {/* Right Side: Recharts simulated outputs */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <div className="flex justify-between items-center border-b border-slate-900/60 pb-3">
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">Pass Rate Yield Projection</h3>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="bg-slate-950/80 border border-slate-850 p-4 rounded-xl text-center">
                <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Yield Projection</span>
                <div className="text-3xl font-extrabold text-indigo-400 mt-1 font-mono">{currentPassRate}%</div>
              </div>
              <div className="bg-slate-950/80 border border-slate-850 p-4 rounded-xl text-center">
                <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Calibration Ratio</span>
                <div className="text-3xl font-extrabold text-white mt-1 font-mono">
                  {Math.round(timeout / temp / 10)}
                </div>
              </div>
              <div className="bg-slate-950/80 border border-slate-850 p-4 rounded-xl text-center">
                <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Quality Confidence</span>
                <div className="text-lg font-bold text-emerald-400 mt-2 uppercase tracking-wide">
                  {currentPassRate >= 80 ? 'Authoritative' : currentPassRate >= 60 ? 'Standard' : 'Volatile'}
                </div>
              </div>
            </div>

            <div className="h-60 w-full pt-4">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorPass" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#6366f1" stopOpacity={0.2} />
                      <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" opacity={0.3} />
                  <XAxis dataKey="name" stroke="#475569" fontSize={9} />
                  <YAxis stroke="#475569" fontSize={9} />
                  <Tooltip contentStyle={{ backgroundColor: '#020617', borderColor: '#1e293b', fontSize: '10px' }} />
                  <Area type="monotone" dataKey="PassRate" stroke="#6366f1" fillOpacity={1} fill="url(#colorPass)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
