const { useState, useEffect, useMemo } = React;

// --- Icon Helpers ---
const Icon = ({ name, size = 20, className = "" }) => {
    // Simplified lucide-like icons using SVG
    const icons = {
        home: <> <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></>,
        scenarios: <> <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></>,
        editor: <> <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></>,
        debugger: <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>,
        docs: <> <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></>,
        search: <> <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></>,
        plus: <> <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></>,
        play: <polygon points="5 3 19 12 5 21 5 3"/>,
        check: <polyline points="20 6 9 17 4 12"/>,
        alert: <> <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></>,
        fileText: <> <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></>,
        activity: <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>,
        book: <> <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></>,
        box: <> <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></>,
        github: <> <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/></>,
        chart: <> <path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></>
    };
    const iconName = name === 'bar-chart-2' ? 'chart' : 
                     name === 'file-text' ? 'fileText' : 
                     name === 'activity' ? 'activity' :
                     name === 'book' ? 'book' :
                     name === 'box' ? 'box' :
                     name === 'github' ? 'github' : name;
    return (
        <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
            {icons[iconName] || icons.home}
        </svg>
    );
};

// --- Components ---

const Sidebar = ({ activeTab, setActiveTab, navItems }) => (
    <div className="w-64 bg-[#0d1117] border-r border-slate-800 flex flex-col h-full overflow-y-auto">
        <div className="p-6 mb-4">
            <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center text-white font-bold shadow-lg shadow-blue-500/20">
                    <Icon name="debugger" size={24} />
                </div>
                <div>
                    <h1 className="font-bold text-slate-100 tracking-tight">OpenCore</h1>
                    <p className="text-[10px] text-slate-500 font-medium uppercase tracking-widest">Admin Console</p>
                </div>
            </div>
        </div>
        
        <nav className="flex-1 px-3 space-y-1">
            {navItems.map(item => (
                <button
                    key={item.id}
                    onClick={() => setActiveTab(item.id)}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                        activeTab === item.id 
                        ? 'bg-blue-600/10 text-blue-400 border border-blue-500/10' 
                        : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200 border border-transparent'
                    }`}
                >
                    <Icon name={item.icon} size={18} />
                    {item.title}
                </button>
            ))}
        </nav>
        
        <div className="p-4 border-t border-slate-800">
            <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-800">
                <p className="text-[10px] text-slate-500 uppercase font-bold tracking-widest mb-1">Status</p>
                <div className="flex items-center gap-2">
                    <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse"></div>
                    <span className="text-xs text-slate-300 font-medium">Core API Online</span>
                </div>
            </div>
        </div>
    </div>
);

const ScenarioExplorer = ({ onNotify, searchQuery = "" }) => {
    const [scenarios, setScenarios] = useState([]);
    const [query, setQuery] = useState('');
    const [loading, setLoading] = useState(true);

    const fetchScenarios = () => {
        setLoading(true);
        fetch(`/api/scenarios?q=${query}`)
            .then(res => res.json())
            .then(data => {
                setScenarios(data.scenarios || []);
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
            });
    };

    useEffect(() => {
        const delayDebounceFn = setTimeout(() => {
            fetchScenarios();
        }, 300);
        return () => clearTimeout(delayDebounceFn);
    }, [query]);

    const filteredScenarios = searchQuery 
        ? scenarios.filter(s => 
            s.title.toLowerCase().includes(searchQuery.toLowerCase()) || 
            s.scenario_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
            s.industry.toLowerCase().includes(searchQuery.toLowerCase())
          )
        : scenarios;

    const handleRunEval = (scenario) => {
        fetch('/api/evaluate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: scenario.path, scenario_id: scenario.scenario_id })
        })
        .then(res => res.json())
        .then(data => {
            onNotify(`${data.message || 'Evaluation queued successfully!'}`);
        })
        .catch(err => {
            onNotify(`Error: ${err.message}`, 'error');
        });
    };

    return (
        <div className="p-8 space-y-6 max-w-6xl mx-auto">
            <div className="flex justify-between items-end">
                <div>
                    <h2 className="text-2xl font-bold text-white mb-2">Scenario Explorer</h2>
                    <p className="text-slate-500 text-sm">Browse, search, and execute evaluation scenarios from the catalog.</p>
                </div>
                <div className="relative">
                    <Icon name="search" size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                    <input 
                        type="text"
                        placeholder="Local filter..."
                        className="bg-slate-900 border border-slate-800 rounded-xl py-2 pl-10 pr-4 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all w-64 text-slate-200"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />
                </div>
            </div>

            {loading ? (
                <div className="flex items-center justify-center h-64">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {filteredScenarios.map(s => (
                        <div key={s.scenario_id} className="bg-[#161b22] border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-all group">
                            <div className="flex justify-between items-start mb-4">
                                <div className="p-2 bg-blue-500/10 rounded-lg text-blue-400 group-hover:bg-blue-500 group-hover:text-white transition-all">
                                    <Icon name="scenarios" size={20} />
                                </div>
                                <div className={`px-2 py-1 rounded text-[10px] font-bold uppercase tracking-widest ${
                                    s.lint_score > 80 ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500'
                                }`}>
                                    Quality: {s.lint_score}%
                                </div>
                            </div>
                            <h3 className="text-slate-100 font-bold mb-1 truncate">{s.title}</h3>
                            <p className="text-slate-500 text-xs mb-4">ID: {s.scenario_id}</p>
                            <div className="flex items-center justify-between">
                                <span className="text-[10px] text-slate-400 font-bold uppercase tracking-widest bg-slate-800 px-2 py-1 rounded">{s.industry}</span>
                                <button 
                                    onClick={() => handleRunEval(s)}
                                    className="text-blue-500 hover:text-blue-400 text-xs font-bold flex items-center gap-1 group/btn"
                                >
                                    Run Eval <Icon name="play" size={12} className="group-hover/btn:translate-x-0.5 transition-transform" />
                                </button>
                            </div>
                        </div>
                    ))}
                    {filteredScenarios.length === 0 && (
                        <div className="col-span-full py-12 text-center text-slate-500 italic">No scenarios match your search.</div>
                    )}
                </div>
            )}
        </div>
    );
};

const ScenarioEditor = () => {
    const initialState = {
        scenario_id: 'new_scenario',
        title: 'New Scenario',
        industry: 'generic',
        tasks: [{ id: '1', description: 'Agent should verify user identity' }]
    };
    
    const [scenario, setScenario] = useState(initialState);
    const [generatedJson, setGeneratedJson] = useState(null);

    const addTask = () => {
        setScenario({
            ...scenario,
            tasks: [...scenario.tasks, { id: String(Date.now()), description: '' }]
        });
    };

    const removeTask = (id) => {
        if (scenario.tasks.length > 1) {
            setScenario({
                ...scenario,
                tasks: scenario.tasks.filter(t => t.id !== id)
            });
        }
    };

    const handleReset = () => {
        if (confirm('Are you sure you want to reset the editor?')) {
            setScenario(initialState);
            setGeneratedJson(null);
        }
    };

    const handleGenerate = () => {
        const aes = {
            version: "1.0",
            metadata: {
                scenario_id: scenario.scenario_id,
                title: scenario.title,
                industry: scenario.industry,
                created_at: new Date().toISOString()
            },
            evaluation_sequence: scenario.tasks.map((t, idx) => ({
                step: idx + 1,
                description: t.description,
                required: true
            }))
        };
        setGeneratedJson(JSON.stringify(aes, null, 4));
    };

    return (
        <div className="p-8 space-y-8 max-w-4xl mx-auto">
            <div className="flex justify-between items-start">
                <div>
                    <h2 className="text-2xl font-bold text-white mb-2">Visual AES Builder</h2>
                    <p className="text-slate-500 text-sm">Design complex multi-turn agentic evaluation logic without writing JSON.</p>
                </div>
                {generatedJson && (
                    <button 
                        onClick={() => setGeneratedJson(null)}
                        className="text-xs text-blue-500 font-bold uppercase tracking-widest hover:text-blue-400"
                    >
                        Edit Layout
                    </button>
                )}
            </div>

            {generatedJson ? (
                <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
                    <div className="bg-[#161b22] border border-slate-800 rounded-2xl overflow-hidden shadow-2xl">
                        <div className="px-6 py-3 border-b border-slate-800 bg-slate-800/20 flex justify-between items-center">
                            <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">AES Configuration JSON</span>
                            <button 
                                onClick={() => {
                                    navigator.clipboard.writeText(generatedJson);
                                    alert('Copied to clipboard!');
                                }}
                                className="text-[10px] bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold px-3 py-1.5 rounded transition-colors uppercase tracking-widest"
                            >
                                Copy JSON
                            </button>
                        </div>
                        <pre className="p-8 text-blue-400 font-mono text-sm leading-relaxed overflow-x-auto max-h-[500px] selection:bg-blue-500/20">
                            {generatedJson}
                        </pre>
                    </div>
                </div>
            ) : (
                <>
                    <div className="grid grid-cols-2 gap-6">
                        <div className="space-y-2">
                            <label className="text-xs font-bold text-slate-500 uppercase tracking-widest">Scenario ID</label>
                            <input 
                                type="text" 
                                value={scenario.scenario_id}
                                onChange={(e) => setScenario({ ...scenario, scenario_id: e.target.value })}
                                className="w-full bg-slate-900 border border-slate-800 rounded-xl py-3 px-4 text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-mono"
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-xs font-bold text-slate-500 uppercase tracking-widest">Title</label>
                            <input 
                                type="text" 
                                value={scenario.title}
                                onChange={(e) => setScenario({ ...scenario, title: e.target.value })}
                                className="w-full bg-slate-900 border border-slate-800 rounded-xl py-3 px-4 text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                            />
                        </div>
                    </div>

                    <div className="space-y-4">
                        <label className="text-xs font-bold text-slate-500 uppercase tracking-widest block">Task Sequence (State Nodes)</label>
                        <div className="space-y-3">
                            {scenario.tasks.map((task, idx) => (
                                <div key={task.id} className="flex gap-4 items-center bg-[#161b22] border border-slate-800 rounded-xl p-4 group hover:border-slate-600 transition-all">
                                    <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center text-xs font-bold text-blue-500 border border-slate-700 flex-shrink-0">
                                        {idx + 1}
                                    </div>
                                    <input 
                                        type="text"
                                        placeholder="Describe the expected agent behavior or task..."
                                        value={task.description}
                                        onChange={(e) => {
                                            const newTasks = [...scenario.tasks];
                                            newTasks[idx].description = e.target.value;
                                            setScenario({ ...scenario, tasks: newTasks });
                                        }}
                                        className="flex-1 bg-transparent text-slate-200 border-none focus:outline-none placeholder:text-slate-700 py-1"
                                    />
                                    <button 
                                        onClick={() => removeTask(task.id)}
                                        className="p-2 text-slate-700 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all"
                                        title="Remove Task"
                                    >
                                        <Icon name="plus" size={16} className="rotate-45" />
                                    </button>
                                </div>
                            ))}
                        </div>
                        <button 
                            onClick={addTask}
                            className="w-full py-4 border-2 border-dashed border-slate-800 rounded-xl text-slate-500 hover:text-slate-300 hover:border-slate-600 transition-all flex items-center justify-center gap-2 text-sm font-bold"
                        >
                            <Icon name="plus" size={18} /> Add Evaluation Node
                        </button>
                    </div>

                    <div className="pt-6 border-t border-slate-800 flex justify-end gap-3">
                        <button 
                            onClick={handleReset}
                            className="px-6 py-2.5 rounded-xl border border-slate-800 text-slate-300 font-bold text-sm hover:bg-slate-800 transition-all"
                        >
                            Reset
                        </button>
                        <button 
                            onClick={handleGenerate}
                            className="px-6 py-2.5 rounded-xl bg-blue-600 text-white font-bold text-sm hover:bg-blue-500 transition-all shadow-lg shadow-blue-500/20"
                        >
                            Generate AES JSON
                        </button>
                    </div>
                </>
            )}
        </div>
    );
};

const VisualDebugger = ({ runId, onNotify }) => {
    const [events, setEvents] = useState([]);
    const [selectedEvent, setSelectedEvent] = useState(null);
    const [loading, setLoading] = useState(false);
    const [isLive, setIsLive] = useState(!runId || runId === 'live');

    const loadTrace = (id) => {
        setLoading(true);
        const targetId = id || runId;
        const url = (targetId && targetId !== 'live') 
            ? `/api/debugger/state?run_id=${targetId}`
            : `/api/debugger/state`;

        fetch(url)
            .then(res => res.json())
            .then(data => {
                if (data.data && data.data.timeline) {
                    setEvents(data.data.timeline);
                } else if (Array.isArray(data)) {
                    setEvents(data);
                }
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
            });
    };

    useEffect(() => {
        loadTrace(runId);
    }, [runId]);

    useEffect(() => {
        if (!isLive) return;
        
        const interval = setInterval(() => {
            fetch('/api/debugger/state')
                .then(res => res.json())
                .then(data => {
                    if (data.data && data.data.timeline) {
                        setEvents(data.data.timeline);
                    }
                });
        }, 1000);
        
        return () => clearInterval(interval);
    }, [isLive]);

    const handleExport = () => {
        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(events, null, 2));
        const downloadAnchorNode = document.createElement('a');
        downloadAnchorNode.setAttribute("href", dataStr);
        downloadAnchorNode.setAttribute("download", `trace-${runId || 'export'}.json`);
        document.body.appendChild(downloadAnchorNode);
        downloadAnchorNode.click();
        downloadAnchorNode.remove();
        onNotify("Trace exported as JSON");
    };

    return (
        <div className="flex h-full overflow-hidden">
            {/* Timeline Column */}
            <div className="w-80 border-r border-slate-800 flex flex-col bg-[#0b0e14]">
                <div className="p-4 border-b border-slate-800 sticky top-0 bg-[#0b0e14]/80 backdrop-blur-md z-10 flex justify-between items-center">
                    <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Execution Trace</h3>
                    <div className="flex gap-2">
                        <button onClick={() => loadTrace()} title="Reload Trace" className="text-slate-500 hover:text-blue-400">
                            <Icon name="activity" size={14} />
                        </button>
                        <button onClick={handleExport} title="Export Trace" className="text-slate-500 hover:text-emerald-400">
                            <Icon name="box" size={14} />
                        </button>
                    </div>
                </div>
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    {loading ? (
                        <div className="flex items-center justify-center py-12">
                            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
                        </div>
                    ) : (
                        events.map((e, idx) => (
                        <div 
                            key={idx}
                            onClick={() => setSelectedEvent(e)}
                            className={`p-3 rounded-xl cursor-pointer border transition-all ${
                                selectedEvent === e 
                                ? 'bg-blue-600/10 border-blue-500/30 ring-1 ring-blue-500/20' 
                                : 'bg-[#161b22] border-slate-800 hover:border-slate-700'
                            }`}
                        >
                            <div className="flex justify-between items-start mb-2">
                                <span className={`text-[10px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded ${
                                    e.event === 'prompt' ? 'text-sky-400 bg-sky-400/10' :
                                    e.event === 'agent_response' ? 'text-emerald-400 bg-emerald-400/10' :
                                    e.event === 'tool_call' ? 'text-amber-400 bg-amber-400/10' :
                                    'text-slate-400 bg-slate-400/10'
                                }`}>
                                    {e.event.replace('_', ' ')}
                                </span>
                                <span className="text-[10px] text-slate-600 font-mono italic">
                                    {new Date(e.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                </span>
                            </div>
                            <p className="text-xs text-slate-300 line-clamp-2 leading-relaxed opacity-80">
                                {e.content || (e.tool ? `${e.tool}(...)` : e.scenario || "Run Info")}
                            </p>
                        </div>
                    ))
                    )}
                </div>
            </div>

            {/* Content Column */}
            <div className="flex-1 overflow-y-auto bg-slate-900/10 p-8">
                {selectedEvent ? (
                    <div className="max-w-3xl mx-auto space-y-6">
                        <div className="flex items-center gap-4 border-b border-slate-800 pb-6 mb-6">
                            <div className="w-12 h-12 rounded-2xl bg-slate-800 flex items-center justify-center text-blue-500 border border-slate-700">
                                <Icon name="debugger" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-white capitalize">{selectedEvent.event.replace('_', ' ')}</h3>
                                <p className="text-sm text-slate-500">Raw event data from Flight Recorder</p>
                            </div>
                        </div>

                        <div className="bg-[#161b22] border border-slate-800 rounded-2xl overflow-hidden">
                            <div className="px-6 py-3 border-b border-slate-800 bg-slate-800/20 flex justify-between items-center">
                                <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">JSON Payload</span>
                                <button 
                                    onClick={() => {
                                        navigator.clipboard.writeText(JSON.stringify(selectedEvent, null, 2));
                                        if (onNotify) onNotify("Event JSON copied to clipboard");
                                    }}
                                    className="text-[10px] bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold px-2 py-1 rounded transition-colors uppercase tracking-widest"
                                >
                                    Copy
                                </button>
                            </div>
                            <pre className="p-6 text-emerald-400 font-mono text-sm leading-relaxed overflow-x-auto selection:bg-emerald-500/20">
                                {JSON.stringify(selectedEvent, null, 2)}
                            </pre>
                        </div>
                    </div>
                ) : (
                    <div className="h-full flex flex-col items-center justify-center space-y-4 opacity-50">
                        <div className="w-16 h-16 rounded-3xl bg-slate-800 flex items-center justify-center text-slate-600 scale-110">
                            <Icon name="debugger" size={32} />
                        </div>
                        <p className="text-sm font-medium text-slate-500">Select an event from the timeline to inspect trace state</p>
                    </div>
                )}
            </div>
        </div>
    );
};

const ReportsView = ({ onViewReport }) => {
    const [runs, setRuns] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetch('/api/runs')
            .then(res => res.json())
            .then(data => {
                setRuns(data.runs || []);
                setLoading(false);
            });
    }, []);

    return (
        <div className="p-8 space-y-6 max-w-6xl mx-auto">
            <div>
                <h2 className="text-2xl font-bold text-white mb-2">Reports & Traces</h2>
                <p className="text-slate-500 text-sm">Review historical execution logs and analyzed agent trajectories.</p>
            </div>

            {loading ? (
                <div className="flex items-center justify-center h-64">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                </div>
            ) : (
                <div className="bg-[#161b22] border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
                    <table className="w-full text-left">
                        <thead>
                            <tr className="bg-slate-800/30 text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em] border-b border-slate-800">
                                <th className="px-6 py-4">Timestamp</th>
                                <th className="px-6 py-4">Run ID</th>
                                <th className="px-6 py-4">Scenario</th>
                                <th className="px-6 py-4 text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800">
                            {runs.map(run => (
                                <tr key={run.run_id} className="hover:bg-slate-800/20 transition-colors">
                                    <td className="px-6 py-4 text-xs text-slate-400 font-mono">
                                        {new Date(run.timestamp).toLocaleString()}
                                    </td>
                                    <td className="px-6 py-4 text-xs font-bold text-slate-200">
                                        {run.run_id}
                                    </td>
                                    <td className="px-6 py-4 text-xs text-slate-400">
                                        {run.scenario}
                                    </td>
                                    <td className="px-6 py-4 text-right">
                                        <button 
                                            onClick={() => onViewReport(run.run_id)}
                                            className="text-blue-500 hover:text-blue-400 text-xs font-bold transition-colors"
                                        >
                                            View Report
                                        </button>
                                    </td>
                                </tr>
                            ))}
                            {runs.length === 0 && (
                                <tr>
                                    <td colSpan="4" className="px-6 py-12 text-center text-slate-600 italic text-sm">
                                        No historical runs found in the flight recorder.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

const DocsView = ({ categoryFilter, searchQuery = "" }) => {
    const [docs, setDocs] = useState([]);
    const [selectedDoc, setSelectedDoc] = useState(null);
    const [docContent, setDocContent] = useState('');
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetch('/api/docs')
            .then(res => res.json())
            .then(data => {
                const filtered = categoryFilter 
                    ? data.docs.filter(d => d.category === categoryFilter)
                    : data.docs;
                setDocs(filtered);
                setLoading(false);
            });
    }, [categoryFilter]);

    const filteredDocs = searchQuery 
        ? docs.filter(d => d.title.toLowerCase().includes(searchQuery.toLowerCase()))
        : docs;

    const groupedDocs = useMemo(() => {
        return filteredDocs.reduce((acc, doc) => {
            const cat = doc.category || "Uncategorized";
            if (!acc[cat]) acc[cat] = [];
            acc[cat].push(doc);
            return acc;
        }, {});
    }, [filteredDocs]);

    const readDoc = (id) => {
        setDocContent('');
        setSelectedDoc(id);
        fetch(`/api/docs/${encodeURIComponent(id)}`)
            .then(res => res.json())
            .then(data => setDocContent(data.content || ''));
    };

    if (selectedDoc) {
        return (
            <div className="p-8 max-w-4xl mx-auto space-y-6">
                <button 
                    onClick={() => setSelectedDoc(null)}
                    className="flex items-center gap-2 text-slate-500 hover:text-slate-300 transition-colors text-sm font-bold uppercase tracking-widest"
                >
                    <Icon name="scenarios" size={16} className="rotate-180" /> Back to Guides
                </button>
                <div className="bg-[#161b22] border border-slate-800 rounded-3xl p-10 prose prose-invert prose-slate max-w-none shadow-2xl">
                    <pre className="text-slate-300 whitespace-pre-wrap font-sans leading-relaxed">
                        {docContent || 'Loading document...'}
                    </pre>
                </div>
            </div>
        );
    }

    return (
        <div className="p-8 space-y-8 max-w-6xl mx-auto">
            <div>
                <h2 className="text-2xl font-bold text-white mb-2">
                    {categoryFilter === 'API Reference' ? 'API Reference' : 'Documentation Hub'}
                </h2>
                <p className="text-slate-500 text-sm">Explore architectural patterns, plugin guides, and AES specifications.</p>
            </div>

            {loading ? (
                <div className="flex items-center justify-center h-64">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                </div>
            ) : (
                Object.entries(groupedDocs).map(([category, items]) => (
                    <div key={category} className="space-y-4">
                        <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em] border-l-2 border-blue-600 pl-4">
                            {category}
                        </h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            {items.map(doc => (
                                <div 
                                    key={doc.id}
                                    onClick={() => readDoc(doc.id)}
                                    className="p-5 bg-[#161b22] border border-slate-800 rounded-2xl flex items-center justify-between group cursor-pointer hover:border-blue-500/50 hover:bg-blue-500/5 transition-all"
                                >
                                    <div className="flex items-center gap-4">
                                        <div className="p-2.5 bg-slate-800 rounded-xl text-slate-400 group-hover:bg-blue-600 group-hover:text-white transition-all">
                                            <Icon name="book" size={18} />
                                        </div>
                                        <div>
                                            <h4 className="font-bold text-sm text-white mb-0.5 group-hover:text-blue-400 transition-colors truncate max-w-40">{doc.title}</h4>
                                            <p className="text-[9px] text-slate-600 font-mono">{doc.id.split('/').pop()}</p>
                                        </div>
                                    </div>
                                    <Icon name="play" size={12} className="text-slate-700 group-hover:text-blue-500 transition-all" />
                                </div>
                            ))}
                        </div>
                    </div>
                ))
            )}
            {!loading && Object.keys(groupedDocs).length === 0 && (
                <div className="py-20 text-center text-slate-600 italic">No documentation found.</div>
            )}
        </div>
    );
};

const Dashboard = ({ onNavigate, navItems }) => {
    const [search, setSearch] = useState('');
    
    const statusItems = [
        { label: 'Agent Endpoint', value: 'Connected', icon: 'activity' },
        { label: 'Engine Version', value: 'v1.1.0', icon: 'box' },
        { label: 'Control Plane', value: 'Active', icon: 'check' },
        { label: 'Simulators', value: 'Online', icon: 'debugger' }
    ];

    const filteredStatus = statusItems.filter(item => 
        item.label.toLowerCase().includes(search.toLowerCase()) || 
        item.value.toLowerCase().includes(search.toLowerCase())
    );

    const filteredNav = navItems.filter(item => 
        item.title.toLowerCase().includes(search.toLowerCase())
    );

    return (
    <div className="p-8 space-y-8 max-w-6xl mx-auto">
        <div className="flex justify-between items-center mb-2">
            <h2 className="text-3xl font-bold text-white">Dashboard</h2>
            <div className="relative">
                <Icon name="search" size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input 
                    type="text"
                    placeholder="Search console..."
                    className="bg-slate-900 border border-slate-800 rounded-xl py-2 pl-10 pr-4 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all w-80 text-slate-200"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                />
            </div>
        </div>

        <div className="grid grid-cols-3 gap-6">
            <div className="bg-gradient-to-br from-blue-600 to-indigo-700 rounded-3xl p-6 text-white shadow-xl shadow-blue-500/20 flex flex-col justify-between h-48 border border-white/10">
                <Icon name="play" size={24} className="opacity-50" />
                <div>
                    <h3 className="text-4xl font-black mb-1">100%</h3>
                    <p className="text-sm font-bold opacity-80 uppercase tracking-widest">Recent Pass Rate</p>
                </div>
            </div>
            <div className="bg-[#161b22] border border-slate-800 rounded-3xl p-6 flex flex-col justify-between h-48 shadow-xl">
                <div className="flex justify-between items-start">
                    <Icon name="scenarios" size={24} className="text-slate-500" />
                    <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                </div>
                <div>
                    <h3 className="text-4xl font-black mb-1 text-white">4,621</h3>
                    <p className="text-sm font-bold text-slate-500 uppercase tracking-widest">Scenarios Index</p>
                </div>
            </div>
            <div className="bg-[#161b22] border border-slate-800 rounded-3xl p-6 flex flex-col justify-between h-48 shadow-xl">
                <div className="flex justify-between items-start">
                    <Icon name="debugger" size={24} className="text-slate-500" />
                    <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></div>
                </div>
                <div>
                    <h3 className="text-4xl font-black mb-1 text-white">Online</h3>
                    <p className="text-sm font-bold text-slate-500 uppercase tracking-widest">Active Simulators</p>
                </div>
            </div>
        </div>

        <div>
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em] mb-4">Quick Access & Status</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {filteredStatus.map((item, idx) => (
                    <div key={idx} className="p-6 bg-[#161b22] border border-slate-800 rounded-2xl flex gap-4 items-center animate-in fade-in duration-300">
                        <div className="w-12 h-12 bg-blue-500/10 rounded-2xl flex items-center justify-center text-blue-500 border border-blue-500/20">
                            <Icon name={item.icon} />
                        </div>
                        <div>
                            <h4 className="font-bold text-white mb-0.5">{item.label}</h4>
                            <p className="text-xs text-slate-500">{item.value}</p>
                        </div>
                    </div>
                ))}
            </div>
        </div>

        {filteredNav.length > 0 && (
            <div className="animate-in fade-in slide-in-from-bottom-2 duration-500">
                <h3 className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em] mb-4">Navigation</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
                    {filteredNav.map(item => (
                        <button 
                            key={item.id}
                            onClick={() => onNavigate(item)}
                            className="p-4 bg-[#161b22] border border-slate-800 rounded-2xl hover:border-blue-500/50 hover:bg-blue-500/5 transition-all group flex flex-col items-center text-center"
                        >
                            <div className="p-3 bg-slate-800 rounded-xl mb-3 text-slate-400 group-hover:bg-blue-600 group-hover:text-white transition-all">
                                <Icon name={item.icon} size={20} />
                            </div>
                            <span className="text-xs font-bold text-slate-200 group-hover:text-blue-400">{item.title}</span>
                        </button>
                    ))}
                </div>
            </div>
        )}
    </div>
    );
};

// --- Main App ---

const App = () => {
    const [activeTab, setActiveTab] = useState('dashboard');
    const [navItems, setNavItems] = useState([]);
    const [searching, setSearching] = useState(false);
    const [globalSearch, setGlobalSearch] = useState('');
    const [toast, setToast] = useState(null);
    const [selectedRunId, setSelectedRunId] = useState(null);

    const showToast = (message, type = 'success') => {
        setToast({ message, type });
        setTimeout(() => setToast(null), 3000);
    };

    useEffect(() => {
        fetch('/api/nav')
            .then(res => res.json())
            .then(data => setNavItems(data.nav || []));
            
        // Handle direct navigation from URL on boot
        const path = window.location.pathname.substring(1);
        if (path) setActiveTab(path === 'docs/api' ? 'api_docs' : path);
    }, []);

    const handleNavClick = (item) => {
        if (item.type === 'external') {
            window.open(item.path, '_blank');
        } else {
            setActiveTab(item.id);
            if (item.id !== 'debugger') setSelectedRunId(null);
            window.history.pushState({}, '', `/${item.id === 'dashboard' ? '' : item.id === 'api_docs' ? 'docs/api' : item.id}`);
        }
    };

    const handleViewReport = (runId) => {
        setSelectedRunId(runId);
        setActiveTab('debugger');
        window.history.pushState({}, '', '/debugger');
    };

    const renderContent = () => {
        switch (activeTab) {
            case 'dashboard': return <Dashboard onNavigate={handleNavClick} navItems={navItems} />;
            case 'scenarios': return <ScenarioExplorer onNotify={showToast} searchQuery={globalSearch} />;
            case 'reports': return <ReportsView onViewReport={handleViewReport} />;
            case 'editor': return <ScenarioEditor />;
            case 'debugger': return <VisualDebugger runId={selectedRunId} onNotify={showToast} />;
            case 'docs': return <DocsView searchQuery={globalSearch} />;
            case 'api_docs': return <DocsView categoryFilter="API Reference" searchQuery={globalSearch}  />;
            default: return (
                <div className="h-full flex flex-col items-center justify-center opacity-30 italic">
                    <h2 className="text-5xl font-black mb-4">404</h2>
                    <p>Feature module loading or not available in OpenCore</p>
                </div>
            );
        }
    };

    return (
        <React.Fragment>
            <Sidebar activeTab={activeTab} setActiveTab={(id) => handleNavClick(navItems.find(n => n.id === id))} navItems={navItems} />
            <main className="flex-1 flex flex-col overflow-hidden bg-[#0b0e14]">
                <header className="h-16 border-b border-slate-800 flex items-center justify-between px-8 bg-[#0b0e14]/50 backdrop-blur-xl sticky top-0 z-20">
                    <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">{activeTab.replace('_', ' ')}</span>
                    </div>
                    <div className="flex gap-4">
                        {searching && (
                            <input 
                                autoFocus
                                type="text"
                                placeholder="Global search..."
                                value={globalSearch}
                                onChange={(e) => setGlobalSearch(e.target.value)}
                                onBlur={() => !globalSearch && setSearching(false)}
                                className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-1 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500 w-48"
                            />
                        )}
                        <button 
                            onClick={() => setSearching(!searching)}
                            className={`p-2 rounded-lg transition-colors ${searching ? 'text-blue-400 bg-blue-400/10' : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'}`}
                        >
                            <Icon name="search" size={18} />
                        </button>
                    </div>
                </header>
                <div className="flex-1 overflow-y-auto">
                    {renderContent()}
                </div>
            </main>

            {/* Toast Notification */}
            {toast && (
                <div className="fixed bottom-8 right-8 z-[100] animate-in slide-in-from-right-8 duration-300">
                    <div className={`px-6 py-4 rounded-2xl shadow-2xl flex items-center gap-3 border ${
                        toast.type === 'error' 
                        ? 'bg-red-500/10 border-red-500/20 text-red-500' 
                        : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-500'
                    }`}>
                        <Icon name={toast.type === 'error' ? 'alert' : 'check'} size={18} />
                        <span className="text-sm font-bold tracking-tight">{toast.message}</span>
                    </div>
                </div>
            )}
        </React.Fragment>
    );
};

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
