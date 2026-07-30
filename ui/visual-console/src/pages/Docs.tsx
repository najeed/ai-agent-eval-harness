import React, { useState, useEffect } from 'react';
import { BookOpen, FileText, Search, ChevronRight } from 'lucide-react';

interface DocItem {
  id: string;
  path: string;
  category: string;
}

export const Docs: React.FC = () => {
  const [docsList, setDocsList] = useState<DocItem[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<DocItem | null>(null);
  const [docContent, setDocContent] = useState<string>('');
  const [loadingList, setLoadingList] = useState(true);
  const [loadingContent, setLoadingContent] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const fetchDocs = async () => {
    try {
      const res = await fetch('/api/docs');
      const data = await res.json();
      const list = data.docs || [];
      setDocsList(list);
      if (list.length > 0) {
        setSelectedDoc(list[0]);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingList(false);
    }
  };

  const fetchDocContent = async (doc: DocItem) => {
    setLoadingContent(true);
    try {
      const res = await fetch(`/api/docs/${doc.path}`);
      const data = await res.json();
      setDocContent(data.content || 'No content found.');
    } catch (e: any) {
      setDocContent(`Error loading document: ${e.message}`);
    } finally {
      setLoadingContent(false);
    }
  };

  useEffect(() => {
    fetchDocs();
  }, []);

  useEffect(() => {
    if (selectedDoc) {
      fetchDocContent(selectedDoc);
    }
  }, [selectedDoc]);

  const filteredDocs = docsList.filter(d => 
    d.id.toLowerCase().includes(searchQuery.toLowerCase()) || 
    d.category.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Simple Markdown Formatter for rendering headers, bullet points, tables, code blocks, bold text
  const renderMarkdown = (text: string) => {
    if (!text) return null;
    const lines = text.split('\n');
    let inCodeBlock = false;
    let codeContent: string[] = [];
    let formattedElements: React.ReactNode[] = [];

    lines.forEach((line, index) => {
      if (line.trim().startsWith('```')) {
        if (inCodeBlock) {
          // Close block
          formattedElements.push(
            <pre key={`code-${index}`} className="bg-slate-950/80 border border-slate-800 p-4 rounded-lg text-xs font-mono text-emerald-400 overflow-x-auto my-3 leading-relaxed">
              <code>{codeContent.join('\n')}</code>
            </pre>
          );
          codeContent = [];
          inCodeBlock = false;
        } else {
          // Open block
          inCodeBlock = true;
        }
        return;
      }

      if (inCodeBlock) {
        codeContent.push(line);
        return;
      }

      const trimmed = line.trim();

      // Headers
      if (trimmed.startsWith('# ')) {
        formattedElements.push(<h1 key={index} className="text-2xl font-bold text-white tracking-tight mt-6 mb-3 border-b border-slate-800 pb-2">{trimmed.slice(2)}</h1>);
      } else if (trimmed.startsWith('## ')) {
        formattedElements.push(<h2 key={index} className="text-xl font-bold text-slate-100 tracking-tight mt-5 mb-2">{trimmed.slice(3)}</h2>);
      } else if (trimmed.startsWith('### ')) {
        formattedElements.push(<h3 key={index} className="text-lg font-bold text-slate-200 tracking-tight mt-4 mb-2">{trimmed.slice(4)}</h3>);
      }
      // Bullet list items
      else if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
        formattedElements.push(
          <li key={index} className="ml-6 list-disc text-sm text-slate-350 my-1 leading-relaxed">
            {parseInlineStyles(trimmed.slice(2))}
          </li>
        );
      }
      // Paragraph
      else if (trimmed.length > 0) {
        formattedElements.push(
          <p key={index} className="text-sm text-slate-300 my-2 leading-relaxed">
            {parseInlineStyles(trimmed)}
          </p>
        );
      } else {
        formattedElements.push(<div key={index} className="h-2" />);
      }
    });

    return <div className="space-y-1">{formattedElements}</div>;
  };

  const parseInlineStyles = (text: string) => {
    // Simple inline parser for **bold** and `code`
    const parts = text.split(/(\*\*.*?\*\*|`.*?`)/g);
    return parts.map((part, i) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={i} className="font-semibold text-white">{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith('`') && part.endsWith('`')) {
        return <code key={i} className="bg-slate-950 border border-slate-800 px-1.5 py-0.5 rounded text-xs font-mono text-indigo-400">{part.slice(1, -1)}</code>;
      }
      return part;
    });
  };

  // Group by category
  const categories = Array.from(new Set(filteredDocs.map(d => d.category)));

  return (
    <div className="flex h-screen bg-navy-base text-slate-100 overflow-hidden">
      {/* Sidebar - Document List */}
      <div className="w-80 border-r border-slate-800 flex flex-col bg-slate-950/30 shrink-0">
        <div className="p-4 border-b border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-indigo-400" />
            <h2 className="font-bold text-white text-sm">Documentation</h2>
          </div>
          <div className="relative">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
            <input 
              type="text"
              placeholder="Search guides..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800/80 rounded-lg pl-9 pr-4 py-2 text-xs text-slate-300 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-4">
          {loadingList ? (
            <p className="text-xs text-slate-500 italic p-2">Loading documents...</p>
          ) : categories.length === 0 ? (
            <p className="text-xs text-slate-500 italic p-2">No documents found.</p>
          ) : (
            categories.map(cat => (
              <div key={cat} className="space-y-1">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider px-2.5 py-1 block">
                  {cat}
                </span>
                <div className="space-y-0.5">
                  {filteredDocs.filter(d => d.category === cat).map(doc => (
                    <button
                      key={doc.id}
                      onClick={() => setSelectedDoc(doc)}
                      className={`flex items-center justify-between w-full text-left px-3 py-2 rounded-lg text-xs transition-colors ${
                        selectedDoc?.id === doc.id
                          ? 'bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 font-semibold'
                          : 'border border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/50'
                      }`}
                    >
                      <div className="flex items-center gap-2 truncate">
                        <FileText className="w-3.5 h-3.5 shrink-0 opacity-70" />
                        <span className="truncate">{doc.id.replace(/-/g, ' ')}</span>
                      </div>
                      <ChevronRight className="w-3 h-3 opacity-55" />
                    </button>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Main Panel - Doc Renderer */}
      <div className="flex-1 overflow-y-auto bg-navy-base p-8">
        {selectedDoc ? (
          <div className="max-w-3xl space-y-4">
            <div className="flex items-center gap-2 text-xs font-semibold text-indigo-400 uppercase tracking-wider">
              <span>{selectedDoc.category}</span>
              <span>/</span>
              <span>{selectedDoc.path}</span>
            </div>

            {loadingContent ? (
              <div className="py-12 space-y-2">
                <div className="w-1/3 h-6 bg-slate-800 animate-pulse rounded" />
                <div className="w-full h-4 bg-slate-800 animate-pulse rounded" />
                <div className="w-5/6 h-4 bg-slate-800 animate-pulse rounded" />
                <div className="w-4/5 h-4 bg-slate-800 animate-pulse rounded" />
              </div>
            ) : (
              <div className="prose prose-invert prose-slate max-w-none text-slate-350">
                {renderMarkdown(docContent)}
              </div>
            )}
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-slate-500 italic text-sm">
            Select a document from the sidebar to begin reading.
          </div>
        )}
      </div>
    </div>
  );
};
