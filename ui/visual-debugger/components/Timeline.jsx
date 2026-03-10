import React from 'react';

/**
 * Timeline component for the Visual Debugger.
 * Displays a list of events from run.jsonl.
 */
function Timeline({ events, selectedEvent, onSelect }) {
    return (
        <div className="flex flex-col h-full bg-slate-900 text-slate-300 border-r border-slate-700 overflow-y-auto">
            <div className="p-4 border-b border-slate-700 font-bold uppercase tracking-wider text-xs text-slate-500">
                Execution Timeline
            </div>
            <div className="flex-1">
                {events.map((event, index) => {
                    const isSelected = selectedEvent === event;
                    return (
                        <div
                            key={index}
                            className={`p-3 cursor-pointer border-b border-slate-800 transition-colors hover:bg-slate-800 ${isSelected ? 'bg-blue-600/20 border-l-4 border-l-blue-500' : ''
                                }`}
                            onClick={() => onSelect(event)}
                        >
                            <div className="flex justify-between items-center mb-1">
                                <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${event.event === 'tool_call' ? 'bg-amber-500/20 text-amber-500' :
                                        event.event === 'agent_response' ? 'bg-green-500/20 text-green-500' :
                                            event.event === 'error' ? 'bg-red-500/20 text-red-500' :
                                                'bg-slate-700 text-slate-400'
                                    }`}>
                                    {event.event}
                                </span>
                                <span className="text-[10px] opacity-50">{new Date(event.timestamp).toLocaleTimeString()}</span>
                            </div>
                            <div className="text-sm truncate">
                                {event.content || event.tool || event.metric || "Details..."}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

export default Timeline;
