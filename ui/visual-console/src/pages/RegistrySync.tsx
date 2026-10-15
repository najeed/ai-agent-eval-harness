import React, { useState, useEffect } from 'react';
import { useRBAC } from '../context/RBACContext';
import { Search, ChevronDown, ChevronRight, BookOpen, Sparkles, RefreshCw } from 'lucide-react';

interface Standard {
  id: string;
  name: string;
  description: string;
}

interface Category {
  description: string;
  standards: Record<string, Standard>;
}

interface RegistryData {
  industries: Record<string, Category>;
}

export const RegistrySync: React.FC = () => {
  const { role, canAccessSettings } = useRBAC();
  const [data, setData] = useState<RegistryData | null>(null);
  const [search, setSearch] = useState('');
  const [expandedCategories, setExpandedCategories] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Add standard form inputs
  const [newId, setNewId] = useState('');
  const [newName, setNewName] = useState('');
  const [newIndustry, setNewIndustry] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newCat, setNewCat] = useState('');
  const [adding, setAdding] = useState(false);
  const [addMsg, setAddMsg] = useState('');
  const [addError, setAddError] = useState('');

  const fetchRegistry = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/registry');
      const json = await res.json();
      if (res.ok) {
        setData(json);
        // Pre-expand top level industries
        if (json.industries) {
          const initialExpanded: Record<string, boolean> = {};
          Object.keys(json.industries).forEach((key) => {
            initialExpanded[key] = true;
          });
          setExpandedCategories(initialExpanded);
        }
      } else {
        setError(json.error || 'Failed to load standards registry.');
      }
    } catch (err: any) {
      setError(err.message || 'Network error fetching registry.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRegistry();
  }, []);

  const toggleCategory = (cat: string) => {
    setExpandedCategories((prev) => ({ ...prev, [cat]: !prev[cat] }));
  };

  const handleAddStandard = async (e: React.FormEvent) => {
    e.preventDefault();
    setAdding(true);
    setAddMsg('');
    setAddError('');
    try {
      const res = await fetch('/api/registry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: newId,
          name: newName,
          industry: newIndustry,
          description: newDesc,
          category: newCat || undefined
        })
      });
      const json = await res.json();
      if (res.ok) {
        setAddMsg(json.message || 'Standard added successfully.');
        setNewId('');
        setNewName('');
        setNewIndustry('');
        setNewDesc('');
        setNewCat('');
        // Re-load registry
        fetchRegistry();
      } else {
        setAddError(json.error || 'Failed to add standard.');
      }
    } catch (err: any) {
      setAddError(err.message || 'Network error connecting to registry API.');
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-indigo-400" />
            <span>Registry Sync</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Synchronize scenario validation frameworks with external regulatory reference standards. Gated enum metadata changes propagate globally across harness engines.
          </p>
        </div>
        <button
          onClick={fetchRegistry}
          className="p-2 bg-slate-950 border border-slate-900 rounded-lg text-slate-400 hover:text-slate-200 transition-colors"
          title="Refresh Registry"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Side: Adding Gated Standards */}
        <div className="space-y-6 lg:col-span-1">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <span>Add Custom Standard</span>
            </h3>

            {!canAccessSettings ? (
              <div className="p-3.5 bg-slate-900/50 border border-slate-850 rounded-lg text-slate-500 text-[11px] leading-relaxed italic text-center">
                * View-Only Access: "{role}" permissions are insufficient to add regulatory references to the schema catalog.
              </div>
            ) : (
              <form onSubmit={handleAddStandard} className="space-y-3">
                <div className="space-y-1">
                  <label className="text-[9px] text-slate-500 font-bold uppercase">Standard ID (Unique Enum)</label>
                  <input
                    type="text"
                    value={newId}
                    onChange={(e) => setNewId(e.target.value)}
                    placeholder="e.g. GDPR-SEC-01"
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-350 focus:outline-none focus:border-indigo-500 font-mono"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[9px] text-slate-500 font-bold uppercase">Standard Name</label>
                  <input
                    type="text"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="e.g. GDPR Data Integrity Control"
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-350 focus:outline-none focus:border-indigo-500"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[9px] text-slate-500 font-bold uppercase">Target Industry</label>
                  <input
                    type="text"
                    value={newIndustry}
                    onChange={(e) => setNewIndustry(e.target.value)}
                    placeholder="e.g. finance, healthcare, legal"
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-350 focus:outline-none focus:border-indigo-500"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[9px] text-slate-500 font-bold uppercase">Description</label>
                  <textarea
                    value={newDesc}
                    onChange={(e) => setNewDesc(e.target.value)}
                    placeholder="Describe the compliance rule constraints..."
                    className="w-full h-20 bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-350 focus:outline-none focus:border-indigo-500 resize-none"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[9px] text-slate-500 font-bold uppercase">Category Heading (Optional)</label>
                  <input
                    type="text"
                    value={newCat}
                    onChange={(e) => setNewCat(e.target.value)}
                    placeholder="e.g. NIST Privacy or empty"
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-350 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                {addMsg && (
                  <div className="p-2.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded text-[10px] font-bold">
                    {addMsg}
                  </div>
                )}
                {addError && (
                  <div className="p-2.5 bg-rose-500/10 border border-rose-500/25 text-rose-400 rounded text-[10px] font-bold">
                    {addError}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={adding}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors"
                >
                  {adding ? 'Adding Reference...' : 'Add Standard & Sync'}
                </button>
              </form>
            )}
          </div>
        </div>

        {/* Right Side: Tree Registry standards browser */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-slate-950/60 border border-slate-900 rounded-xl p-3 flex items-center gap-3">
            <Search className="w-5 h-5 text-slate-500 shrink-0" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search reference standards by ID or description..."
              className="flex-1 bg-transparent border-none text-slate-200 text-xs focus:outline-none placeholder-slate-600"
            />
          </div>

          {error && (
            <div className="p-4 bg-rose-500/10 border border-rose-500/25 rounded-xl text-rose-400 text-xs">
              {error}
            </div>
          )}

          {loading ? (
            <div className="flex justify-center items-center py-20 text-xs text-slate-500">
              Loading active registry index...
            </div>
          ) : !data || Object.keys(data.industries).length === 0 ? (
            <div className="bg-slate-950/15 border border-slate-900 border-dashed rounded-xl p-16 text-center text-slate-500">
              No standards currently configured.
            </div>
          ) : (
            <div className="space-y-3">
              {Object.entries(data.industries).map(([indName, category]) => {
                const standards = Object.values(category.standards || {});
                // Filter standards based on search query
                const filteredStandards = standards.filter((s) => {
                  const query = search.toLowerCase();
                  return (
                    s.id.toLowerCase().includes(query) ||
                    s.name.toLowerCase().includes(query) ||
                    s.description.toLowerCase().includes(query)
                  );
                });

                if (filteredStandards.length === 0) return null;
                const isExpanded = expandedCategories[indName];

                return (
                  <div
                    key={indName}
                    className="bg-slate-950/30 border border-slate-900 rounded-xl overflow-hidden"
                  >
                    {/* Category Title bar */}
                    <button
                      onClick={() => toggleCategory(indName)}
                      className="w-full flex items-center justify-between p-4 bg-slate-950/50 hover:bg-slate-950/80 transition-colors border-b border-slate-900 text-left"
                    >
                      <div>
                        <h4 className="text-xs font-bold text-slate-200 capitalize">{indName}</h4>
                        <p className="text-[10px] text-slate-500 mt-0.5">{category.description}</p>
                      </div>
                      {isExpanded ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
                    </button>

                    {/* Standard Leaf Items */}
                    {isExpanded && (
                      <div className="p-3 space-y-2.5 bg-slate-950/10">
                        {filteredStandards.map((std) => (
                          <div
                            key={std.id}
                            className="bg-slate-950/60 border border-slate-850 p-3 rounded-lg flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 hover:border-slate-800 transition-colors"
                          >
                            <div className="space-y-1">
                              <div className="flex items-center gap-2">
                                <span className="font-mono text-xs font-bold text-indigo-400 bg-indigo-500/5 px-2 py-0.5 rounded border border-indigo-500/10">
                                  {std.id}
                                </span>
                                <h5 className="text-xs font-bold text-slate-200">{std.name}</h5>
                              </div>
                              <p className="text-[10px] text-slate-400 leading-relaxed font-sans">{std.description}</p>
                            </div>
                            <span className="shrink-0 inline-flex items-center gap-1 text-[8px] bg-slate-900 border border-slate-800 px-2 py-0.5 rounded font-extrabold text-slate-500 font-mono tracking-wider">
                              Enum Sync: OK
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
