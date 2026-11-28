import React, { useState } from 'react';
import { ClipOut } from '@/types/forensic';
import { api } from '@/lib/api';

interface TransactionsViewProps {
  clips: ClipOut[];
  onSelectClip?: (clip: ClipOut) => void;
  onNavigate: (view: string) => void;
}

export const TransactionsView: React.FC<TransactionsViewProps> = ({ clips, onSelectClip, onNavigate }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [atmFilter, setAtmFilter] = useState('all');
  const [copiedSha, setCopiedSha] = useState<string | null>(null);

  const filteredClips = clips.filter((c) => {
    const q = searchTerm.toLowerCase();
    const matchesSearch =
      c.original_filename.toLowerCase().includes(q) ||
      (c.atm_id && c.atm_id.toLowerCase().includes(q)) ||
      c.sha256.toLowerCase().includes(q) ||
      (c.notes && c.notes.toLowerCase().includes(q));

    const matchesAtm = atmFilter === 'all' || c.atm_id === atmFilter;
    return matchesSearch && matchesAtm;
  });

  const handleCopySha = (sha: string) => {
    navigator.clipboard.writeText(sha);
    setCopiedSha(sha);
    setTimeout(() => setCopiedSha(null), 2000);
  };

  const atmList = Array.from(new Set(clips.map((c) => c.atm_id).filter(Boolean))) as string[];

  return (
    <section id="view-transactions" className="space-y-4 max-w-[1440px] mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 tracking-tight">ATM Surveillance Footage &amp; Clips</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Indexed ATM CCTV video captures with SHA-256 integrity digests, terminal assignments, and container streams.
          </p>
        </div>
        <button
          onClick={() => onNavigate('ingest')}
          className="px-3.5 py-1.5 text-xs font-semibold bg-steel hover:bg-steel-hover text-white rounded flex items-center gap-1.5 transition-colors self-start sm:self-auto shadow-sm"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          Ingest New Footage
        </button>
      </div>

      {/* Multi-Facet Filter Bar */}
      <div className="bg-white border border-hairline rounded-md p-3.5 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <svg
            className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <input
            id="txnSearchInput"
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search clip filename, Terminal ID, or SHA-256 hash..."
            className="w-full pl-8 pr-3 py-1.5 text-xs bg-canvas border border-hairline rounded text-slate-900 placeholder-slate-400 focus:outline-none focus:border-steel focus:bg-white font-mono"
          />
        </div>

        {/* ATM Terminal Filter */}
        <select
          value={atmFilter}
          onChange={(e) => setAtmFilter(e.target.value)}
          className="px-2.5 py-1.5 text-xs bg-white border border-hairline rounded text-slate-700 focus:outline-none focus:border-steel"
        >
          <option value="all">Terminal: All ATMs</option>
          {atmList.map((atm) => (
            <option key={atm} value={atm}>
              {atm}
            </option>
          ))}
        </select>

        <span className="font-mono text-xs text-slate-500 tabular-nums">
          {filteredClips.length} clips indexed
        </span>
      </div>

      {/* Clips Table */}
      <div className="bg-white border border-hairline rounded-md overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-canvas border-b border-hairline text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                <th className="py-2.5 px-4 w-12">Stream</th>
                <th className="py-2.5 px-4">Clip Filename</th>
                <th className="py-2.5 px-4">Terminal</th>
                <th className="py-2.5 px-4">Recording Start</th>
                <th className="py-2.5 px-4">Format / Specs</th>
                <th className="py-2.5 px-4">Duration</th>
                <th className="py-2.5 px-4">SHA-256 Digest</th>
                <th className="py-2.5 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline text-xs font-mono">
              {filteredClips.map((clip) => (
                <tr key={clip.id} className="hover:bg-slate-50/70 transition-colors">
                  <td className="py-3 px-4">
                    <div className="w-9 h-7 rounded bg-slate-900 flex items-center justify-center text-slate-400 overflow-hidden shrink-0">
                      <svg className="w-4 h-4 text-slate-400" viewBox="0 0 24 24" fill="currentColor">
                        <polygon points="5 3 19 12 5 21 5 3"></polygon>
                      </svg>
                    </div>
                  </td>
                  <td className="py-3 px-4 font-semibold text-slate-900">
                    <div className="truncate max-w-[200px]" title={clip.original_filename}>
                      {clip.original_filename}
                    </div>
                    <div className="text-[10px] text-slate-400 font-normal">
                      {clip.notes || 'Forensic ATM review'}
                    </div>
                  </td>
                  <td className="py-3 px-4">
                    <span className="px-2 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-700 text-[11px]">
                      {clip.atm_id || 'ATM-JPR-014'}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-slate-600">
                    {clip.clip_start_time ? clip.clip_start_time.replace('T', ' ').substring(0, 19) : '2026-11-26 21:14:00'}
                  </td>
                  <td className="py-3 px-4 text-slate-600">
                    {clip.width}×{clip.height} @ {clip.fps || 25}fps
                    <span className="text-[10px] text-slate-400 block">{clip.codec || 'H.264'} / {clip.container || 'mp4'}</span>
                  </td>
                  <td className="py-3 px-4 text-slate-700 tabular-nums">
                    {clip.duration_sec ? `${clip.duration_sec.toFixed(1)}s` : '36.0s'}
                  </td>
                  <td className="py-3 px-4">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[11px] text-slate-500 font-mono truncate max-w-[120px]" title={clip.sha256}>
                        {clip.sha256.substring(0, 12)}...
                      </span>
                      <button
                        onClick={() => handleCopySha(clip.sha256)}
                        className="text-slate-400 hover:text-steel text-[10px]"
                        title="Copy SHA-256"
                      >
                        {copiedSha === clip.sha256 ? '✓' : 'Copy'}
                      </button>
                    </div>
                  </td>
                  <td className="py-3 px-4 text-right">
                    <button
                      onClick={() => {
                        if (onSelectClip) onSelectClip(clip);
                        onNavigate('inspector');
                      }}
                      className="px-2.5 py-1 text-xs font-semibold bg-white border border-steel text-steel hover:bg-steel-tint rounded transition-colors"
                    >
                      Inspect
                    </button>
                  </td>
                </tr>
              ))}
              {filteredClips.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-xs text-slate-400 font-mono">
                    No surveillance clips matched current filter criteria.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
};
