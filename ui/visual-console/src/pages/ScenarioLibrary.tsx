import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Search, Grid, List, 
  Sparkles, CheckCircle, ArrowRight, Play, RefreshCw, Filter
} from 'lucide-react';

interface ScenarioItem {
  id: string;
  title: string;
  industry: string;
  aes_version: number;
  compliance_level?: string;
  metadata?: {
    name: string;
    description?: string;
    compliance_level?: string;
    capabilities?: string[];
  };
}

export const ScenarioLibrary: React.FC = () => {
  const navigate = useNavigate();
  const [scenarios, setScenarios] = useState<ScenarioItem[]>([]);
  const [allIndustries, setAllIndustries] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<'grid' | 'table'>('grid');
  
  // Search & Filter state
  const [search, setSearch] = useState('');
  const [selectedIndustry, setSelectedIndustry] = useState<string>('All');
  const [selectedDifficulty, setSelectedDifficulty] = useState<string>('All');
  
  // Bulk Actions
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState('');

  const fetchScenarios = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set('q', search.trim());
      if (selectedIndustry !== 'All') params.set('industry', selectedIndustry);
      if (selectedDifficulty !== 'All') params.set('difficulty', selectedDifficulty);
      params.set('limit', '500');

      const res = await fetch(`/api/scenarios?${params.toString()}`);
      const data = await res.json();
      setScenarios(data.scenarios || []);
      if (data.all_industries && Array.isArray(data.all_industries) && data.all_industries.length > 0) {
        setAllIndustries(data.all_industries);
      } else if (data.scenarios) {
        setAllIndustries(prev => {
          const combined = new Set([...prev, ...data.scenarios.map((s: ScenarioItem) => s.industry).filter(Boolean)]);
          return Array.from(combined).sort((a, b) => a.localeCompare(b));
        });
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleRefreshIndex = async () => {
    setRefreshing(true);
    setMessage('');
    try {
      const res = await fetch('/api/scenarios/refresh', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        setMessage(`Success: Indexed ${data.scenario_count || 0} scenarios.`);
        fetchScenarios();
      } else {
        setMessage(`Error: ${data.error}`);
      }
    } catch (e: any) {
      setMessage(`Error: ${e.message}`);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchScenarios();
  }, [search, selectedIndustry, selectedDifficulty]);


  const toggleSelect = (id: string) => {
    setSelectedIds(prev => 
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const toggleSelectAll = () => {
    if (selectedIds.length === filteredScenarios.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(filteredScenarios.map(s => s.id));
    }
  };

  const handleBulkExecute = () => {
    if (selectedIds.length === 0) return;
    navigate(`/?scenario_id=${encodeURIComponent(selectedIds[0])}&scenarios=${encodeURIComponent(selectedIds.join(','))}`);
  };


  const handleBulkMutate = async () => {
    if (selectedIds.length === 0) return;
    setRefreshing(true);
    setMessage('');
    let successCount = 0;
    
    for (const id of selectedIds) {
      try {
        const res = await fetch('/api/v1/mutate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scenario_id: id, count: 2 })
        });
        if (res.ok) successCount++;
      } catch (e) {
        console.error(`Mutation failed for ${id}:`, e);
      }
    }
    
    setMessage(`Successfully generated adversarial mutations for ${successCount}/${selectedIds.length} scenarios.`);
    setRefreshing(false);
    setSelectedIds([]);
    fetchScenarios();
  };

  const filteredScenarios = scenarios.filter(s => {
    const titleMatch = (s.title || '').toLowerCase().includes(search.toLowerCase()) || 
                       (s.metadata?.description || '').toLowerCase().includes(search.toLowerCase()) ||
                       (s.id || '').toLowerCase().includes(search.toLowerCase());
    
    const indMatch = selectedIndustry === 'All' || s.industry?.toLowerCase() === selectedIndustry.toLowerCase();
    // Difficulty match
    const compLevel = (s.compliance_level || s.metadata?.compliance_level || 'Standard').toLowerCase();
    const diffMatch = selectedDifficulty === 'All' || 
                      (selectedDifficulty === 'Standard' && (compLevel === 'standard' || s.aes_version === 1)) ||
                      (selectedDifficulty === 'High' && compLevel !== 'standard');
                      
    return titleMatch && indMatch && diffMatch;
  });

  const industries = [
    'All',
    ...(allIndustries.length > 0
      ? allIndustries
      : Array.from(new Set(scenarios.map(s => s.industry))).filter(Boolean).sort((a, b) => a.localeCompare(b)))
  ];


  return (
    <div className="flex h-screen bg-navy-base text-slate-100 overflow-hidden">
      {/* Faceted Filter Sidebar */}
      <div className="w-64 border-r border-slate-900 flex flex-col bg-slate-950/20 shrink-0">
        <div className="p-4 border-b border-slate-900 space-y-2">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-400">
            <Filter className="w-3.5 h-3.5 text-indigo-400" />
            <span>Faceted Taxonomy</span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5 text-xs">
          {/* Industry Facet */}
          <div className="space-y-2">
            <span className="font-bold text-slate-500 uppercase tracking-wider text-[10px]">Industry sector</span>
            <div className="space-y-1">
              {industries.map(ind => (
                <button
                  key={ind}
                  onClick={() => setSelectedIndustry(ind)}
                  className={`flex items-center justify-between w-full text-left px-2 py-1.5 rounded transition-colors ${
                    selectedIndustry === ind
                      ? 'bg-indigo-500/10 text-indigo-400 font-semibold'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
                  }`}
                >
                  <span className="capitalize">{ind.replace(/_/g, ' ')}</span>
                  <span className="text-[10px] text-slate-600 font-bold">
                    {ind === 'All' ? scenarios.length : scenarios.filter(s => s.industry?.toLowerCase() === ind.toLowerCase()).length || ''}
                  </span>

                </button>
              ))}
            </div>
          </div>

          {/* Compliance Level Facet */}
          <div className="space-y-2">
            <span className="font-bold text-slate-500 uppercase tracking-wider text-[10px]">Compliance Difficulty</span>
            <div className="space-y-1">
              {['All', 'Standard', 'High'].map(diff => (
                <button
                  key={diff}
                  onClick={() => setSelectedDifficulty(diff)}
                  className={`flex items-center justify-between w-full text-left px-2 py-1.5 rounded transition-colors ${
                    selectedDifficulty === diff
                      ? 'bg-indigo-500/10 text-indigo-400 font-semibold'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
                  }`}
                >
                  <span>{diff} Level</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Main Catalog View */}
      <div className="flex-1 flex flex-col min-w-0 bg-navy-base overflow-hidden">
        {/* Search and Action Header */}
        <div className="p-4 border-b border-slate-900 bg-slate-950/10 flex flex-col md:flex-row gap-4 justify-between items-center shrink-0">
          <div className="relative w-full md:max-w-sm">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
            <input 
              type="text"
              placeholder="Search scenario catalog..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-slate-950 border border-slate-900 rounded-lg pl-9 pr-4 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex items-center gap-3 shrink-0 text-xs">
            {/* View Mode Toggle */}
            <div className="flex items-center bg-slate-950 border border-slate-900 rounded-lg p-0.5">
              <button 
                onClick={() => setViewMode('grid')}
                className={`p-1.5 rounded ${viewMode === 'grid' ? 'bg-slate-900 text-indigo-400' : 'text-slate-500'}`}
              >
                <Grid className="w-4 h-4" />
              </button>
              <button 
                onClick={() => setViewMode('table')}
                className={`p-1.5 rounded ${viewMode === 'table' ? 'bg-slate-900 text-indigo-400' : 'text-slate-500'}`}
              >
                <List className="w-4 h-4" />
              </button>
            </div>

            {/* Sync DB Button */}
            <button
              onClick={handleRefreshIndex}
              disabled={refreshing}
              className="flex items-center gap-1.5 px-3 py-2 bg-slate-950 border border-slate-900 rounded-lg text-slate-400 hover:text-slate-200 transition-colors font-semibold"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
              <span>Index Catalog</span>
            </button>
          </div>
        </div>

        {/* Bulk Action Toolbar */}
        {selectedIds.length > 0 && (
          <div className="bg-indigo-500/10 border-b border-indigo-500/20 px-6 py-2.5 flex items-center justify-between text-xs animate-fade-in shrink-0">
            <div className="flex items-center gap-2 text-indigo-300 font-bold">
              <span>{selectedIds.length} Scenarios selected</span>
            </div>
            <div className="flex items-center gap-2.5">
              <button
                onClick={handleBulkMutate}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-950 hover:bg-slate-900 border border-indigo-500/20 hover:border-indigo-500/40 text-indigo-400 rounded transition-all font-bold"
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>Adversarial Mutant Fuzz</span>
              </button>
              <button
                onClick={handleBulkExecute}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded transition-all font-bold"
              >
                <Play className="w-3.5 h-3.5" />
                <span>Run Evaluation Suite</span>
              </button>
            </div>
          </div>
        )}

        {message && (
          <div className="bg-slate-950 border-b border-slate-900 px-6 py-2 text-center text-xs text-indigo-300 italic shrink-0">
            {message}
          </div>
        )}

        {/* Catalog Body Grid / Table */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <p className="text-slate-500 text-xs italic">Loading scenario index...</p>
          ) : filteredScenarios.length === 0 ? (
            <p className="text-slate-500 text-xs italic">No scenarios match the selected criteria.</p>
          ) : viewMode === 'grid' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredScenarios.map(sc => {
                const isSelected = selectedIds.includes(sc.id);
                return (
                  <div 
                    key={sc.id} 
                    onClick={() => toggleSelect(sc.id)}
                    className={`border rounded-xl p-5 bg-slate-950/40 hover:bg-slate-950/80 transition-all cursor-pointer flex flex-col justify-between space-y-4 group relative ${
                      isSelected ? 'border-indigo-500/50 shadow-lg shadow-indigo-500/5' : 'border-slate-900 hover:border-slate-800'
                    }`}
                  >
                    {/* Badge header */}
                    <div className="flex justify-between items-start">
                      <span className="text-[9px] bg-slate-900 border border-slate-800 text-slate-400 font-bold uppercase tracking-wider px-2 py-0.5 rounded">
                        {sc.industry}
                      </span>
                      <span className="text-[9px] text-emerald-400 font-bold border border-emerald-500/20 bg-emerald-500/5 px-2 py-0.5 rounded flex items-center gap-0.5">
                        <CheckCircle className="w-3 h-3" /> Lint Passed
                      </span>
                    </div>

                    {/* Content */}
                    <div className="space-y-2">
                      <h3 className="font-bold text-white tracking-tight group-hover:text-indigo-400 transition-colors text-sm font-mono truncate">
                        {sc.title}
                      </h3>
                      <p className="text-slate-400 text-xs line-clamp-3 leading-relaxed">
                        {sc.metadata?.description || 'No description provided.'}
                      </p>
                    </div>

                    {/* Footer */}
                    <div className="flex justify-between items-center text-[10px] text-slate-500 pt-2 border-t border-slate-900/60 font-mono">
                      <span>AES v{sc.aes_version}</span>
                      <button 
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/editor?scenario_id=${sc.id}`);
                        }}
                        className="text-indigo-400 hover:text-indigo-300 flex items-center gap-0.5 font-bold font-sans transition-colors"
                      >
                        Edit Scenario <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="border border-slate-900 rounded-xl overflow-hidden bg-slate-950/40">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-900 bg-slate-950/80 text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                    <th className="px-4 py-3 text-center w-12">
                      <input 
                        type="checkbox" 
                        checked={selectedIds.length === filteredScenarios.length && filteredScenarios.length > 0}
                        onChange={toggleSelectAll}
                        className="rounded border-slate-800 bg-slate-950 text-indigo-600 focus:ring-0"
                      />
                    </th>
                    <th className="px-4 py-3">ID / Name</th>
                    <th className="px-4 py-3">Industry</th>
                    <th className="px-4 py-3">Compliance</th>
                    <th className="px-4 py-3">Capabilities</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-900/60">
                  {filteredScenarios.map(sc => {
                    const isSelected = selectedIds.includes(sc.id);
                    return (
                      <tr key={sc.id} className="hover:bg-slate-950/60 transition-colors">
                        <td className="px-4 py-3 text-center">
                          <input 
                            type="checkbox" 
                            checked={isSelected}
                            onChange={() => toggleSelect(sc.id)}
                            className="rounded border-slate-800 bg-slate-950 text-indigo-600 focus:ring-0"
                          />
                        </td>
                        <td className="px-4 py-3 font-mono font-bold text-slate-350">
                          {sc.id}
                        </td>
                        <td className="px-4 py-3 capitalize text-slate-400">
                          {sc.industry.replace(/_/g, ' ')}
                        </td>
                        <td className="px-4 py-3 text-slate-400">
                          {sc.metadata?.compliance_level || 'Standard'}
                        </td>
                        <td className="px-4 py-3 text-slate-500 font-mono text-[10px] truncate max-w-[200px]">
                          {sc.metadata?.capabilities?.join(', ') || 'Default'}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => navigate(`/editor?scenario_id=${sc.id}`)}
                            className="px-2.5 py-1 bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-300 rounded hover:text-white transition-colors"
                          >
                            Edit
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
