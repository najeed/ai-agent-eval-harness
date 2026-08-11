import React, { useEffect, useState } from 'react';
import { Command } from 'cmdk';
import { useNavigate } from 'react-router-dom';
import { 
  Home, FileText, Play, Activity, BarChart2, ShieldCheck, 
  Settings, BookOpen, Sparkles, Search
} from 'lucide-react';

interface CommandPaletteProps {
  isOpen: boolean;
  setIsOpen: (isOpen: boolean) => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({ isOpen, setIsOpen }) => {
  const navigate = useNavigate();
  const [scenarios, setScenarios] = useState<{ id: string; title: string }[]>([]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setIsOpen(!isOpen);
      }
    };

    document.addEventListener('keydown', down);
    return () => document.removeEventListener('keydown', down);
  }, [isOpen, setIsOpen]);

  useEffect(() => {
    if (isOpen) {
      fetch('/api/scenarios')
        .then(res => res.json())
        .then(data => {
          setScenarios(data.scenarios || []);
        })
        .catch(err => console.error('Failed to load scenarios for command palette:', err));
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const runCommand = (action: () => void) => {
    action();
    setIsOpen(false);
  };

  return (
    <div 
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={() => setIsOpen(false)}
    >
      <div 
        className="bg-slate-900 border border-slate-800 rounded-xl max-w-xl w-full shadow-2xl overflow-hidden text-slate-100"
        onClick={(e) => e.stopPropagation()}
      >
        <Command label="Global Command Menu">
          <div className="flex items-center border-b border-slate-800 px-3 py-2.5">
            <Search className="w-5 h-5 text-slate-400 mr-2" />
            <Command.Input 
              placeholder="Type a command or search page..." 
              className="w-full bg-transparent border-0 outline-none placeholder-slate-500 text-slate-100 focus:ring-0 text-sm font-sans"
            />
          </div>

          <Command.List className="max-h-[300px] overflow-y-auto p-2 space-y-1">
            <Command.Empty className="py-6 text-center text-sm text-slate-500">
              No results found.
            </Command.Empty>

            <Command.Group heading="Navigation" className="text-xs font-semibold text-slate-500 px-2 py-1 uppercase tracking-wider font-sans">
              <Command.Item 
                onSelect={() => runCommand(() => navigate('/'))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer text-sm text-slate-355 hover:bg-indigo-500 hover:text-white transition-colors"
              >
                <Home className="w-4 h-4 text-indigo-400" />
                <span>Dashboard Overview</span>
              </Command.Item>
              <Command.Item 
                onSelect={() => runCommand(() => navigate('/scenarios'))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer text-sm text-slate-355 hover:bg-indigo-500 hover:text-white transition-colors"
              >
                <FileText className="w-4 h-4 text-indigo-400" />
                <span>Scenario Library</span>
              </Command.Item>
              <Command.Item 
                onSelect={() => runCommand(() => navigate('/editor'))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer text-sm text-slate-355 hover:bg-indigo-500 hover:text-white transition-colors"
              >
                <Sparkles className="w-4 h-4 text-indigo-400" />
                <span>Scenario Composer (Visual Editor)</span>
              </Command.Item>
              <Command.Item 
                onSelect={() => runCommand(() => navigate('/runner'))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer text-sm text-slate-355 hover:bg-indigo-500 hover:text-white transition-colors"
              >
                <Play className="w-4 h-4 text-indigo-400" />
                <span>Evaluation Runner</span>
              </Command.Item>
              <Command.Item 
                onSelect={() => runCommand(() => navigate('/debugger'))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer text-sm text-slate-355 hover:bg-indigo-500 hover:text-white transition-colors"
              >
                <Activity className="w-4 h-4 text-indigo-400" />
                <span>Live Trace & Visual Debugger</span>
              </Command.Item>
              <Command.Item 
                onSelect={() => runCommand(() => navigate('/reports'))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer text-sm text-slate-355 hover:bg-indigo-500 hover:text-white transition-colors"
              >
                <BarChart2 className="w-4 h-4 text-indigo-400" />
                <span>Runs & Reports</span>
              </Command.Item>
              <Command.Item 
                onSelect={() => runCommand(() => navigate('/trust'))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer text-sm text-slate-355 hover:bg-indigo-500 hover:text-white transition-colors"
              >
                <ShieldCheck className="w-4 h-4 text-indigo-400" />
                <span>Trust Center (Certify / Verify)</span>
              </Command.Item>
            </Command.Group>

            {scenarios.length > 0 && (
              <Command.Group heading="Scenario Catalog Quick Links" className="text-xs font-semibold text-slate-500 px-2 py-1 uppercase tracking-wider mt-2 font-sans">
                {scenarios.map(sc => (
                  <Command.Item 
                    key={sc.id}
                    onSelect={() => runCommand(() => navigate(`/editor?scenario_id=${sc.id}`))}
                    className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer text-sm text-slate-355 hover:bg-indigo-500 hover:text-white transition-colors font-mono"
                  >
                    <FileText className="w-4 h-4 text-slate-500" />
                    <span>{sc.id} ({sc.title})</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            <Command.Group heading="Utility Actions" className="text-xs font-semibold text-slate-500 px-2 py-1 uppercase tracking-wider mt-2 font-sans">
              <Command.Item 
                onSelect={() => runCommand(() => navigate('/settings'))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer text-sm text-slate-355 hover:bg-indigo-500 hover:text-white transition-colors"
              >
                <Settings className="w-4 h-4 text-indigo-400" />
                <span>System Settings & Cleanup</span>
              </Command.Item>
              <Command.Item 
                onSelect={() => runCommand(() => navigate('/docs'))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer text-sm text-slate-355 hover:bg-indigo-500 hover:text-white transition-colors"
              >
                <BookOpen className="w-4 h-4 text-indigo-400" />
                <span>Developer Guides & Docs</span>
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </div>
  );
};
export default CommandPalette;
