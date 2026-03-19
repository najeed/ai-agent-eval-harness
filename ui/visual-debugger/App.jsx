const { useState, useEffect, useMemo } = React;
const ReactFlowRenderer = window.ReactFlow || {};
const { ReactFlow, Controls, Background, useReactFlow, ReactFlowProvider } = ReactFlowRenderer;

// --- Icon Helpers ---
const Icon = ({ name, size = 20, className = "" }) => {
    // Simplified lucide-like icons using SVG
    const icons = {
        home: <> <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></>,
        scenarios: <> <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" /><polyline points="14 2 14 8 20 8" /></>,
        editor: <> <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></>,
        debugger: <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />,
        docs: <> <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></>,
        search: <> <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></>,
        plus: <> <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></>,
        play: <polygon points="5 3 19 12 5 21 5 3" />,
        check: <polyline points="20 6 9 17 4 12" />,
        alert: <> <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></>,
        fileText: <> <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" /><polyline points="14 2 14 8 20 8" /></>,
        activity: <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />,
        book: <> <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></>,
        box: <> <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" /><polyline points="3.27 6.96 12 12.01 20.73 6.96" /><line x1="12" y1="22.08" x2="12" y2="12" /></>,
        github: <> <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7 A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" /></>,
        chart: <> <path d="M18 20V10" /><path d="M12 20V4" /><path d="M6 20v-6" /></>,
        chevronLeft: <polyline points="15 18 9 12 15 6" />,
        chevronRight: <polyline points="9 18 15 12 9 6" />,
        x: <> <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></>
    };
    const iconName = name === 'bar-chart-2' ? 'chart' :
        name === 'chevron-left' ? 'chevronLeft' :
            name === 'chevron-right' ? 'chevronRight' :
                name === 'x' ? 'x' :
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
                    className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${activeTab === item.id
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
            s.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
            s.industry.toLowerCase().includes(searchQuery.toLowerCase())
        )
        : scenarios;

    const handleRunEval = (scenario) => {
        fetch('/api/evaluate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: scenario.path, id: scenario.id })
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
                        placeholder="Search by ID, title, or industry..."
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
                        <div key={s.id} className="bg-[#161b22] border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-all group">
                            <div className="flex justify-between items-start mb-4">
                                <div className="p-2 bg-blue-500/10 rounded-lg text-blue-400 group-hover:bg-blue-500 group-hover:text-white transition-all">
                                    <Icon name="scenarios" size={20} />
                                </div>
                                <div className={`px-2 py-1 rounded text-[10px] font-bold uppercase tracking-widest ${s.lint_score > 80 ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500'
                                    }`}>
                                    Quality: {s.lint_score}%
                                </div>
                            </div>
                            <h3 className="text-slate-100 font-bold mb-1 truncate">{s.title}</h3>
                            <p className="text-slate-500 text-xs mb-4">ID: {s.id}</p>
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
                                <div
                                    key={task.id}
                                    draggable="true"
                                    onDragStart={(e) => e.dataTransfer.setData('text/plain', idx)}
                                    onDragOver={(e) => e.preventDefault()}
                                    onDrop={(e) => {
                                        e.preventDefault();
                                        const fromIdx = parseInt(e.dataTransfer.getData('text/plain'));
                                        const toIdx = idx;
                                        if (fromIdx === toIdx) return;
                                        const newTasks = [...scenario.tasks];
                                        const [movedTask] = newTasks.splice(fromIdx, 1);
                                        newTasks.splice(toIdx, 0, movedTask);
                                        setScenario({ ...scenario, tasks: newTasks });
                                    }}
                                    className="flex gap-4 items-center bg-[#161b22] border border-slate-800 rounded-xl p-4 group hover:border-slate-600 transition-all cursor-grab active:cursor-grabbing"
                                >
                                    <div className="flex items-center gap-3">
                                        <div className="text-slate-600 group-hover:text-slate-400 transition-colors">
                                            <Icon name="activity" size={14} /> {/* Using activity as a placeholder for drag handle */}
                                        </div>
                                        <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center text-xs font-bold text-blue-500 border border-slate-700 flex-shrink-0">
                                            {idx + 1}
                                        </div>
                                    </div>
                                    <input
                                        type="text"
                                        placeholder="e.g., The agent should calculate the net profit after tax..."
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

// --- New Components for UX Overhaul ---

const HumanFriendlyDetail = ({ event, onNotify }) => {
    const [showRaw, setShowRaw] = useState(false);
    if (!event) return null;

    const renderAgentRequest = (e) => (
        <div className="space-y-4">
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-2">User / User Proxy Request</h4>
                <p className="text-slate-300 whitespace-pre-wrap text-sm leading-relaxed">{e.content || (e.payload && e.payload.task_description)}</p>
            </div>
            <div className="grid grid-cols-2 gap-4">
                <div className="bg-slate-800/30 rounded-lg p-3">
                    <span className="text-[10px] text-slate-500 block uppercase font-bold mb-1">Target Agent</span>
                    <span className="text-sm text-slate-200">{e.agent_name || e.agent || "System Dispatcher"}</span>
                </div>
                <div className="bg-slate-800/30 rounded-lg p-3">
                    <span className="text-[10px] text-slate-500 block uppercase font-bold mb-1">Protocol</span>
                    <span className="text-sm text-slate-200 uppercase">{e.protocol || "Internal"}</span>
                </div>
            </div>
        </div>
    );

    const renderPrompt = (e) => (
        <div className="space-y-4">
            <div className="bg-sky-500/5 border border-sky-500/20 rounded-xl p-4">
                <h4 className="text-xs font-bold text-sky-400 uppercase tracking-widest mb-2">Instructions / Prompt</h4>
                <p className="text-slate-300 whitespace-pre-wrap text-sm leading-relaxed">{e.content}</p>
            </div>
            {e.scenario && (
                <div className="grid grid-cols-2 gap-4">
                    <div className="bg-slate-800/30 rounded-lg p-3">
                        <span className="text-[10px] text-slate-500 block uppercase font-bold mb-1">Scenario</span>
                        <span className="text-sm text-slate-200">{e.scenario}</span>
                    </div>
                </div>
            )}
        </div>
    );

    const renderToolCall = (e) => (
        <div className="space-y-4">
            <div className="flex items-center gap-2 mb-2">
                <div className="p-2 bg-amber-500/10 rounded-lg text-amber-500">
                    <Icon name="box" size={16} />
                </div>
                <h4 className="text-lg font-bold text-white font-mono">{e.tool}(...)</h4>
            </div>
            <div className="space-y-2">
                <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">Arguments</span>
                <pre className="json-block text-amber-400">{JSON.stringify(e.arguments || e.params || {}, null, 2)}</pre>
            </div>
            {e.response && (
                <div className="space-y-2">
                    <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">Response</span>
                    <pre className="json-block text-emerald-400">{JSON.stringify(e.response, null, 2)}</pre>
                </div>
            )}
        </div>
    );

    const renderAgentResponse = (e) => (
        <div className="space-y-4">
            <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-xl p-4">
                <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-widest mb-2">Agent Thought / Output</h4>
                <p className="text-slate-300 whitespace-pre-wrap text-sm leading-relaxed">{e.content || (e.response && e.response.content)}</p>
            </div>
            {e.response && e.response.action && (
                <div className="bg-slate-800/30 rounded-lg p-3 flex justify-between items-center">
                    <div>
                        <span className="text-[10px] text-slate-500 block uppercase font-bold mb-1">Action Taken</span>
                        <span className="text-sm text-blue-400 font-mono font-bold">{e.response.action}</span>
                    </div>
                    {e.response.confidence && (
                        <div className="text-right">
                            <span className="text-[10px] text-slate-500 block uppercase font-bold mb-1">Confidence</span>
                            <span className="text-sm text-emerald-500 font-bold">{(e.response.confidence * 100).toFixed(0)}%</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    );

    const renderWorldState = (e) => (
        <div className="space-y-4">
            <div className="grid grid-cols-1 gap-4">
                <div className="space-y-2">
                    <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">Modified State Paths</span>
                    <div className="flex flex-wrap gap-2">
                        {Object.keys(e.state || {}).map(path => (
                            <span key={path} className="px-2 py-1 bg-blue-500/10 text-blue-400 text-[10px] font-mono rounded border border-blue-500/20">{path}</span>
                        ))}
                        {Object.keys(e.state || {}).length === 0 && <span className="text-slate-600 italic text-xs">No state modifications in this step</span>}
                    </div>
                </div>
                <div className="space-y-2">
                    <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">Full State Diff</span>
                    <pre className="json-block text-sky-400 max-h-64">{JSON.stringify(e.state, null, 2)}</pre>
                </div>
            </div>
        </div>
    );

    return (
        <div className="detail-card animate-in fade-in zoom-in-95 duration-300">
            <div className="detail-header">
                <div className="flex items-center gap-3">
                    <span className={`label-pill ${event.event === 'prompt' ? 'bg-sky-500/10 text-sky-400' :
                        event.event === 'agent_response' ? 'bg-emerald-500/10 text-emerald-400' :
                            event.event === 'tool_call' ? 'bg-amber-500/10 text-amber-400' :
                                event.event === 'agent_request' ? 'bg-slate-500/20 text-slate-300' :
                                    'bg-slate-500/10 text-slate-400'
                        }`}>
                        {event.event.replace('_', ' ')}
                    </span>
                    <span className="text-xs text-slate-500 font-mono">{new Date(event.timestamp).toLocaleTimeString()}</span>
                </div>
                <div className="flex items-center gap-4">
                    <button
                        onClick={() => setShowRaw(!showRaw)}
                        className="text-[10px] text-slate-500 hover:text-white uppercase font-bold tracking-widest flex items-center gap-1 transition-colors"
                    >
                        <Icon name={showRaw ? 'eye_off' : 'eye'} size={12} /> {showRaw ? 'Hide JSON' : 'Show JSON'}
                    </button>
                    <button
                        onClick={() => {
                            navigator.clipboard.writeText(JSON.stringify(event, null, 2));
                            if (onNotify) onNotify("Event JSON copied");
                        }}
                        className="text-[10px] text-slate-500 hover:text-white uppercase font-bold tracking-widest flex items-center gap-1 transition-colors"
                    >
                        <Icon name="box" size={12} /> Copy JSON
                    </button>
                </div>
            </div>

            <div className="detail-body">
                {showRaw ? (
                    <pre className="json-block text-slate-400">{JSON.stringify(event, null, 2)}</pre>
                ) : (
                    <React.Fragment>
                        {event.event === 'prompt' && renderPrompt(event)}
                        {event.event === 'agent_request' && renderAgentRequest(event)}
                        {event.event === 'tool_call' && renderToolCall(event)}
                        {event.event === 'agent_response' && renderAgentResponse(event)}
                        {event.event === 'world_state_change' && renderWorldState(event)}
                        {!['prompt', 'agent_request', 'tool_call', 'agent_response', 'world_state_change'].includes(event.event) && (
                            <pre className="json-block text-slate-400">{JSON.stringify(event, null, 2)}</pre>
                        )}
                    </React.Fragment>
                )}
            </div>
        </div>
    );
};

const FlowContainer = ({ events, onNodeSelect, selectedEvent, highlightFailure, minimal, rootCauseIndex }) => {
    const { setCenter } = useReactFlow();

    const initialNodes = useMemo(() => {
        const nodes = [];
        const COLS = 4;
        const SPACING_X = 250;
        const SPACING_Y = 180;

        events.forEach((idx_e, idx) => {
            const e = events[idx];
            const row = Math.floor(idx / COLS);
            const col = idx % COLS;

            // S-curve logic: alternate direction for even/odd rows
            const adjustedCol = (row % 2 === 0) ? col : (COLS - 1 - col);
            const x = adjustedCol * SPACING_X;
            const y = row * SPACING_Y;

            const isSelected = selectedEvent &&
                selectedEvent.timestamp === e.timestamp &&
                selectedEvent.event === e.event;

            const isFailure = (e.event === 'policy_violation' || e.error || (e.response && e.response.status === 'error') || e.is_root_cause === true || (rootCauseIndex !== -1 && Number(idx) === Number(rootCauseIndex)));

            let nodeClass = `react-flow__node-${(e.event === 'prompt' || e.event === 'agent_request') ? 'prompt' : (e.event === 'tool_call' || e.event === 'agent_response' || e.event === 'agent_thought') ? 'agent' : 'environment'}`;

            if (highlightFailure && isFailure) {
                nodeClass += " ring-4 ring-red-500 ring-offset-8 animate-pulse shadow-[0_0_30px_rgba(239,68,68,0.8)] z-50";
            } else if (isSelected) {
                nodeClass += " ring-2 ring-blue-500 ring-offset-4 ring-offset-[#0d1117] shadow-[0_0_20px_rgba(59,130,246,0.5)] z-50";
            } else if (highlightFailure && !isFailure) {
                nodeClass += " opacity-10 grayscale scale-75";
            } else if (minimal && !isSelected) {
                nodeClass += " opacity-20 grayscale scale-90";
            }

            nodes.push({
                id: `node-${idx}`,
                type: 'default',
                data: {
                    label: (
                        <div className="flex flex-col items-center gap-1 text-center">
                            <span className="text-[10px] font-black text-white leading-tight">
                                {e.tool || (e.event === 'agent_response' ? (e.response?.action || 'Thoughts') : e.payload?.task_description || e.content?.substring(0, 24) || e.event.replace('_', ' '))}
                            </span>
                            <span className="text-[7px] uppercase opacity-60 font-bold tracking-tighter">{e.event.replace('_', ' ')}</span>
                        </div>
                    )
                },
                position: { x: x, y: y },
                className: nodeClass,
                sourcePosition: (row % 2 === 0) ? 'right' : 'left',
                targetPosition: (row % 2 === 0) ? 'left' : 'right',
                // Handle wrap-around connections
                ...(col === COLS - 1 && (idx + 1) % COLS !== 0 ? { sourcePosition: 'bottom' } : {}),
                ...(col === 0 && idx % COLS === 0 && row > 0 ? { targetPosition: 'top' } : {}),
                style: isSelected ? { background: '#1e293b', borderColor: '#3b82f6', color: '#fff', zIndex: 100 } : {}
            });
        });
        return nodes;
    }, [events, selectedEvent, highlightFailure, rootCauseIndex]);

    const initialEdges = useMemo(() => {
        const edges = [];
        for (let i = 0; i < events.length - 1; i++) {
            edges.push({
                id: `edge-${i}`,
                source: `node-${i}`,
                target: `node-${i + 1}`,
                animated: events[i + 1].event === 'tool_call',
                style: { stroke: '#475569', strokeWidth: 2 },
            });
        }
        return edges;
    }, [events]);

    useEffect(() => {
        if (selectedEvent) {
            const idx = events.findIndex(e => e.timestamp === selectedEvent.timestamp && e.event === selectedEvent.event);
            if (idx !== -1) {
                const node = initialNodes[idx];
                // Use a small timeout to ensure ReactFlow is ready to pan
                const timer = setTimeout(() => {
                    setCenter(node.position.x + 50, node.position.y + 25, { zoom: 1.2, duration: 800 });
                }, 100);
                return () => clearTimeout(timer);
            }
        }
    }, [selectedEvent, events, setCenter, initialNodes]);

    const onNodeClick = (event, node) => {
        const idx = parseInt(node.id.split('-')[1]);
        onNodeSelect(events[idx]);
    };

    return (
        <div className="flex-1 h-full">
            <ReactFlow
                nodes={initialNodes}
                edges={initialEdges}
                onNodeClick={onNodeClick}
                fitView
                className="bg-dot-white/[0.05]"
            >
                <Background color="#334155" variant="dots" gap={20} size={1} />
                <Controls showInteractive={false} />
            </ReactFlow>
        </div>
    );
};

const FlowView = ({ events, selectedEvent, onNodeSelect, highlightFailure = false, minimal = false, rootCauseIndex = -1 }) => {
    return (
        <ReactFlowProvider>
            <FlowContainer
                events={events}
                onNodeSelect={onNodeSelect}
                selectedEvent={selectedEvent}
                highlightFailure={highlightFailure}
                minimal={minimal}
                rootCauseIndex={rootCauseIndex}
            />
        </ReactFlowProvider>
    );
};

const VisualDebugger = ({ runId, onNotify = () => { }, minimal = false, hideTimeline = false, highlightFailure = false }) => {
    const [events, setEvents] = useState([]);
    const [selectedEvent, setSelectedEvent] = useState(null);
    const [loading, setLoading] = useState(false);
    const [isLive, setIsLive] = useState(!runId || runId === 'live');
    const [viewMode, setViewMode] = useState('flow');
    const [rootCause, setRootCause] = useState(null);

    // Sync live/historical mode whenever runId prop changes
    useEffect(() => {
        setIsLive(!runId || runId === 'live');
    }, [runId]);

    const loadTrace = (id) => {
        setLoading(true);
        const targetId = id || runId;
        const url = (targetId && targetId !== 'live')
            ? `/api/debugger/state?run_id=${targetId}`
            : `/api/debugger/state`;

        fetch(url)
            .then(res => res.json())
            .then(data => {
                const eventsList = data.events || (data.data && data.data.timeline) || (Array.isArray(data) ? data : []);
                const rc = data.data && data.data.root_cause;
                setEvents(eventsList);
                setRootCause(rc || null);
                
                const rcIdx = rc ? rc.index : -1;

                // Root Cause Isolation logic
                if (eventsList.length > 0) {
                    let targetEvent = eventsList[0];
                    if (highlightFailure) {
                        if (rcIdx !== undefined && rcIdx >= 0) {
                            targetEvent = eventsList[rcIdx];
                        } else {
                            const failureNode = eventsList.find(e =>
                                e.is_root_cause === true ||
                                e.event === 'policy_violation' ||
                                e.error ||
                                (e.response && e.response.status === 'error')
                            );
                            if (failureNode) {
                                targetEvent = failureNode;
                            } else {
                                // Heuristic: if run_end says status=failed, highlight the last agent response
                                const runEnd = eventsList.find(e => e.event === 'run_end' && e.status === 'failed');
                                if (runEnd) {
                                    const lastAction = [...eventsList].reverse().find(e => e.event === 'agent_response' || e.event === 'tool_call');
                                    if (lastAction) targetEvent = lastAction;
                                }
                            }
                        }
                    }
                    setSelectedEvent(targetEvent);
                }
                setLoading(false);
            })
            .catch(err => {
                setLoading(false);
            });
    };

    useEffect(() => {
        loadTrace(runId);
    }, [runId, highlightFailure]);

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
            {!hideTimeline && (
                <div className="w-80 border-r border-slate-800 flex flex-col bg-[#0b0e14]">
                    <div className="p-4 border-b border-slate-800 sticky top-0 bg-[#0b0e14]/80 backdrop-blur-md z-10 flex justify-between items-center">
                        <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Execution Trace</h3>
                        <div className="flex gap-2">
                            <button
                                onClick={() => setViewMode(viewMode === 'list' ? 'flow' : 'list')}
                                title={viewMode === 'flow' ? "Switch to List View" : "Switch to Flow Map"}
                                className={`p-1.5 rounded-lg border transition-all ${viewMode === 'flow' ? 'text-blue-400 bg-blue-400/10 border-blue-400/20' : 'text-slate-500 hover:text-blue-400 border-slate-800'}`}
                            >
                                <Icon name={viewMode === 'flow' ? 'list' : 'activity'} size={14} />
                            </button>
                            <div className="w-px h-4 bg-slate-800 mx-1 self-center" />
                            <button onClick={() => loadTrace()} title="Reload Trace" className="p-1.5 text-slate-500 hover:text-blue-400">
                                <Icon name="check" size={14} />
                            </button>
                            <button onClick={handleExport} title="Export Trace" className="p-1.5 text-slate-500 hover:text-emerald-400">
                                <Icon name="box" size={14} />
                            </button>
                            <div className="w-px h-4 bg-slate-800 mx-1 self-center" />
                            {(rootCause?.index >= 0 || events.some(e => e.is_root_cause || e.event === 'policy_violation' || e.error || (e.response && e.response.status === 'error'))) && (
                                <button
                                    onClick={() => {
                                        if (rootCause?.index >= 0 && events[rootCause.index]) {
                                            setSelectedEvent(events[rootCause.index]);
                                            const confidencePercent = Math.round(rootCause.confidence * 100);
                                            onNotify(`Isolated root cause (${confidencePercent}% confidence): ${rootCause.reason}`);
                                        } else {
                                            // Fallback to local heuristic
                                            const failureNode = events.find(e =>
                                                e.is_root_cause === true ||
                                                e.event === 'policy_violation' ||
                                                e.error ||
                                                (e.response && e.response.status === 'error')
                                            );
                                            if (failureNode) {
                                                setSelectedEvent(failureNode);
                                                onNotify("Focused on isolated root cause");
                                            } else {
                                                const runEnd = events.find(e => e.event === 'run_end' && e.status === 'failed');
                                                if (runEnd) {
                                                    const lastAction = [...events].reverse().find(e => e.event === 'agent_response' || e.event === 'tool_call');
                                                    if (lastAction) {
                                                        setSelectedEvent(lastAction);
                                                        onNotify("Isolated probable root cause (heuristic)");
                                                        return;
                                                    }
                                                }
                                                onNotify("No clear root cause detected in trace", "error");
                                            }
                                        }
                                    }}
                                    title="Isolate Root Cause"
                                    className="p-1.5 text-red-400 hover:text-red-300 bg-red-400/10 rounded-lg border border-red-400/20"
                                >
                                    <Icon name="alert" size={14} />
                                </button>
                            )}
                        </div>
                    </div>
                    <div className="flex-1 overflow-y-auto p-4 space-y-4">
                        {loading ? (
                            <div className="flex items-center justify-center py-12">
                                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
                            </div>
                        ) : events.length > 0 ? (
                            events.map((e, idx) => (
                                <div
                                    key={idx}
                                    onClick={() => setSelectedEvent(e)}
                                    className={`p-3 rounded-xl cursor-pointer border transition-all ${selectedEvent === e
                                        ? 'bg-blue-600/10 border-blue-500/30'
                                        : 'bg-[#161b22] border-slate-800 hover:border-slate-700'
                                        }`}
                                >
                                    <div className="flex justify-between items-start mb-2">
                                        <span className={`text-[10px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded ${(e.event === 'prompt' || e.event === 'agent_request') ? 'text-sky-400 bg-sky-400/10' :
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
                        ) : (
                            <div className="flex flex-col items-center justify-center h-full py-12 text-center space-y-4 opacity-30">
                                <Icon name="activity" size={48} />
                                <p className="text-xs font-bold uppercase tracking-widest">No Trace Loaded</p>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Content Column */}
            <div className="flex-1 overflow-hidden flex flex-col bg-[#0d1117] relative">
                {events.length === 0 ? (
                    <div className="flex-1 flex flex-col items-center justify-center text-center p-12 space-y-6">
                        <div className="w-24 h-24 bg-blue-600/10 rounded-[32px] flex items-center justify-center text-blue-600 border border-blue-600/20 shadow-2xl animate-pulse">
                            <Icon name="debugger" size={48} />
                        </div>
                        <div className="max-w-md">
                            <h3 className="text-2xl font-black text-white mb-2">Debugger Offline</h3>
                            <p className="text-slate-500 text-sm leading-relaxed">
                                Please select a historical run from the **Reports** view or trigger a live evaluation from the **Scenario Explorer** to begin debugging.
                            </p>
                        </div>
                    </div>
                ) : viewMode === 'flow' ? (
                    <FlowView
                        events={events}
                        selectedEvent={selectedEvent}
                        onNodeSelect={(e) => { setSelectedEvent(e); }}
                        highlightFailure={highlightFailure}
                        minimal={minimal}
                        rootCauseIndex={rootCause?.index ?? -1}
                    />
                ) : (
                    <div className="flex-1 overflow-y-auto p-12">
                        {selectedEvent ? (
                            <div className="max-w-4xl mx-auto">
                                <HumanFriendlyDetail event={selectedEvent} onNotify={onNotify} />
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
                )}
            </div>
        </div>
    );
};

const ReportsView = ({ onViewReport, searchQuery = "" }) => {
    const [runs, setRuns] = useState([]);
    const [query, setQuery] = useState('');
    const [loading, setLoading] = useState(true);

    const fetchRuns = () => {
        setLoading(true);
        fetch(`/api/runs?q=${query}`)
            .then(res => res.json())
            .then(data => {
                setRuns(data.runs || []);
                setLoading(false);
            })
            .catch(err => {
                setLoading(false);
            });
    };

    useEffect(() => {
        const delayDebounceFn = setTimeout(() => {
            fetchRuns();
        }, 300);
        return () => clearTimeout(delayDebounceFn);
    }, [query]);

    const filteredRuns = searchQuery
        ? runs.filter(r =>
            r.run_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
            r.scenario.toLowerCase().includes(searchQuery.toLowerCase())
        )
        : runs;

    return (
        <div className="p-8 space-y-6 max-w-6xl mx-auto">
            <div className="flex justify-between items-end">
                <div>
                    <h2 className="text-2xl font-bold text-white mb-2">Reports & Traces</h2>
                    <p className="text-slate-500 text-sm">Review historical execution logs and analyzed agent trajectories.</p>
                </div>
                <div className="relative">
                    <Icon name="search" size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                    <input
                        type="text"
                        placeholder="Search by Run ID or Scenario..."
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
                            {filteredRuns.map(run => (
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
    const [scenarioCount, setScenarioCount] = useState('0');
    const [lastSync, setLastSync] = useState(new Date().toLocaleTimeString());
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [systemInfo, setSystemInfo] = useState({ version: 'Loading...', world_shims: 0, status: 'Checking...', agent_endpoint: 'Connecting...' });

    const fetchState = () => {
        fetch('/api/scenarios')
            .then(res => res.json())
            .then(data => {
                setScenarioCount((data.total_count || data.scenarios.length).toLocaleString());
                setLastSync(new Date().toLocaleTimeString());
            })
            .catch(() => setScenarioCount('Err'));

        fetch('/api/info')
            .then(res => res.json())
            .then(data => setSystemInfo(data))
            .catch(() => setSystemInfo({ version: 'Unknown', world_shims: 0, status: 'Offline', agent_endpoint: 'None' }));
    };

    useEffect(() => {
        fetchState();
    }, []);

    const refreshIndex = (e) => {
        e.stopPropagation();
        if (isRefreshing) return;
        setIsRefreshing(true);
        setScenarioCount('...');
        fetch('/api/scenarios/refresh', { method: 'POST' })
            .then(() => {
                fetchState();
                setIsRefreshing(false);
            })
            .catch(() => {
                setIsRefreshing(false);
                fetchState();
            });
    };

    const statusItems = [
        { label: 'Agent Endpoint', value: systemInfo.agent_endpoint || 'Offline', icon: 'activity' },
        { label: 'Engine Version', value: systemInfo.version, icon: 'box' },
        { label: 'Control Plane', value: systemInfo.status === 'active' ? 'Active' : 'Standby', icon: 'check' },
        { label: 'World Shims', value: `${systemInfo.world_shims || 0} Registered`, icon: 'debugger' }
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
                <div>
                    <h2 className="text-3xl font-bold text-white">Dashboard</h2>
                    <p className="text-slate-500 text-sm mt-1">Real-time oversight of your evaluation infrastructure.</p>
                </div>
                <div className="relative">
                    <Icon name="search" size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                    <input
                        type="text"
                        placeholder="Search systems and navigation..."
                        className="bg-slate-900 border border-slate-800 rounded-xl py-2 pl-10 pr-4 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all w-80 text-slate-200"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                    />
                </div>
            </div>

            <div className="grid grid-cols-3 gap-6">
                {/* Demo Story Hero Card */}
                {systemInfo.enable_demo !== false && (
                    <div
                        onClick={() => onNavigate({ id: 'demo', title: 'Demo' })}
                        className="col-span-1 bg-gradient-to-br from-indigo-600 via-blue-600 to-emerald-500 rounded-3xl p-6 text-white shadow-2xl shadow-blue-500/20 flex flex-col justify-between h-48 border border-white/20 cursor-pointer group active:scale-[0.98] transition-all relative overflow-hidden"
                    >
                        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                            <Icon name="play" size={120} />
                        </div>
                        <div className="flex justify-between items-start z-10">
                            <div className="p-2 bg-white/10 rounded-xl backdrop-blur-md border border-white/20">
                                <Icon name="play" size={20} />
                            </div>
                            <span className="text-[10px] font-black uppercase tracking-[0.2em] bg-white/20 px-2 py-1 rounded-full backdrop-blur-md">Interactive Demo</span>
                        </div>
                        <div className="z-10">
                            <h3 className="text-2xl font-black mb-1 group-hover:translate-x-1 transition-transform">Run Demo</h3>
                            <p className="text-xs font-bold opacity-80 uppercase tracking-widest">Loan Approval Failure</p>
                        </div>
                    </div>
                )}

                <div className="bg-[#161b22] border border-slate-800 rounded-3xl p-6 flex flex-col justify-between h-48 shadow-xl relative group">
                    <div className="flex justify-between items-start">
                        <Icon name="scenarios" size={24} className="text-slate-500" />
                        <button
                            onClick={refreshIndex}
                            disabled={isRefreshing}
                            className={`p-1.5 bg-slate-800 rounded-lg text-[9px] font-bold text-slate-400 hover:text-white hover:bg-blue-600 transition-all uppercase tracking-widest active:scale-95 ${isRefreshing ? 'opacity-100 cursor-wait' : 'opacity-0 group-hover:opacity-100'}`}
                        >
                            {isRefreshing ? <div className="animate-spin w-2 h-2 border-b-2 border-white rounded-full"></div> : "Refresh Index"}
                        </button>
                        <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                    </div>
                    <div>
                        <h3 className="text-4xl font-black mb-1 text-white">{scenarioCount}</h3>
                        <div className="flex items-center gap-2">
                            <p className="text-sm font-bold text-slate-500 uppercase tracking-widest">Scenarios Index</p>
                            <span className="text-[9px] font-bold text-emerald-500/60 uppercase tracking-widest px-1.5 py-0.5 bg-emerald-500/5 rounded border border-emerald-500/10">Synced {lastSync}</span>
                        </div>
                    </div>
                </div>
                <div className="bg-[#161b22] border border-slate-800 rounded-3xl p-6 flex flex-col justify-between h-48 shadow-xl">
                    <div className="flex justify-between items-start">
                        <Icon name="debugger" size={24} className="text-slate-500" />
                        <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></div>
                    </div>
                    <div>
                        <h3 className="text-4xl font-black mb-1 text-white">{systemInfo.world_shims || 0}</h3>
                        <p className="text-sm font-bold text-slate-500 uppercase tracking-widest">World Shims</p>
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
    const [isDemoReady, setIsDemoReady] = useState(!!window.Demo);

    useEffect(() => {
        if (isDemoReady) return;
        const interval = setInterval(() => {
            if (window.Demo) {
                setIsDemoReady(true);
                clearInterval(interval);
            }
        }, 100);
        return () => clearInterval(interval);
    }, [isDemoReady]);

    const showToast = (message, type = 'success') => {
        setToast({ message, type });
        setTimeout(() => setToast(null), 3000);
    };

    useEffect(() => {
        fetch('/api/nav')
            .then(res => res.json())
            .then(data => setNavItems(data.nav || []));

        // Security: Global message listener for plugin-to-core communication
        const handleMessage = (event) => {
            // Origin Validation (assuming same-origin for now, but extensible)
            if (event.origin !== window.location.origin) return;

            const { type, payload } = event.data || {};
            if (type === 'NOTIFY') {
                showToast(payload.message, payload.type);
            }
        };

        window.addEventListener('message', handleMessage);

        // Handle direct navigation from URL on boot
        const path = window.location.pathname.substring(1);
        if (path) setActiveTab(path === 'docs/api' ? 'api_docs' : path);

        return () => window.removeEventListener('message', handleMessage);
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
        const currentItem = navItems.find(n => n.id === activeTab);

        // Dynamic Component Handling (Zero-Touch Hot-Swap)
        if (currentItem && currentItem.type === 'component') {
            return (
                <div className="h-full w-full overflow-hidden bg-slate-900/10">
                    <iframe
                        src={currentItem.path}
                        className="w-full h-full border-none"
                        title={currentItem.title}
                        sandbox="allow-scripts allow-forms allow-popups"
                    />
                </div>
            );
        }

        switch (activeTab) {
            case 'dashboard': return <Dashboard onNavigate={handleNavClick} navItems={navItems} />;
            case 'scenarios': return <ScenarioExplorer onNotify={showToast} searchQuery={globalSearch} />;
            case 'reports': return <ReportsView onViewReport={handleViewReport} searchQuery={globalSearch} />;
            case 'editor': return <ScenarioEditor />;
            case 'debugger': return <VisualDebugger runId={selectedRunId} onNotify={showToast} />;
            case 'demo': 
                if (!window.Demo) {
                    return (
                        <div className="h-full flex flex-col items-center justify-center space-y-4">
                            <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
                            <p className="text-slate-500 font-medium animate-pulse">Loading Demo Module...</p>
                        </div>
                    );
                }
                const DemoComp = window.Demo; 
                return <DemoComp />;
            case 'docs': return <DocsView searchQuery={globalSearch} />;
            case 'api_docs': return <DocsView categoryFilter="API Reference" searchQuery={globalSearch} />;
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
                        {(activeTab === 'docs' || activeTab === 'api_docs') && (
                            <>
                                {searching && (
                                    <input
                                        autoFocus
                                        type="text"
                                        placeholder="Search documentation topics..."
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
                            </>
                        )}
                    </div>
                </header>
                <div className="flex-1 overflow-y-auto">
                    {renderContent()}
                </div>
            </main>

            {/* Toast Notification */}
            {toast && (
                <div className="fixed bottom-8 right-8 z-[100] animate-in slide-in-from-right-8 duration-300">
                    <div className={`px-6 py-4 rounded-2xl shadow-2xl flex items-center gap-3 border ${toast.type === 'error'
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
// Inject ReactFlow for UMD usage
window.ReactFlowRenderer = window.ReactFlow;
window.Icon = Icon;
window.VisualDebugger = VisualDebugger;
root.render(<App />);
