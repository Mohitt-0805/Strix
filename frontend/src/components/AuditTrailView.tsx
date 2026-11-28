import React, { useState } from 'react';
import { MockAuditEntry } from '@/lib/mockData';
import { api } from '@/lib/api';

interface AuditTrailViewProps {
  auditLogs: MockAuditEntry[];
}

export const AuditTrailView: React.FC<AuditTrailViewProps> = ({ auditLogs }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [actionFilter, setActionFilter] = useState('all');
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  const filteredLogs = auditLogs.filter((entry) => {
    const q = searchTerm.toLowerCase();
    const matchesSearch =
      entry.investigator.toLowerCase().includes(q) ||
      entry.refId.toLowerCase().includes(q) ||
      entry.details.toLowerCase().includes(q) ||
      entry.hash.toLowerCase().includes(q);

    const matchesAction = actionFilter === 'all' || entry.action.toLowerCase() === actionFilter.toLowerCase();
    return matchesSearch && matchesAction;
  });

  const handleCopy = (hash: string) => {
    navigator.clipboard.writeText(hash);
    setCopiedHash(hash);
    setTimeout(() => setCopiedHash(null), 2000);
  };

  const handleExportCsv = async () => {
    const csvData = await api.exportAuditCsv();
    const blob = new Blob([csvData], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `strix_audit_log_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const getActionBadge = (action: string) => {
    switch (action.toLowerCase()) {
      case 'dossier export':
        return 'bg-steel-tint text-steel border-steel-border';
      case 'frame override':
      case 'frame enhanced':
        return 'bg-purple-50 text-purple-700 border-purple-200';
      case 'flag':
      case 'flag escalation':
        return 'bg-status-crimsonBg text-status-crimson border-status-crimsonBorder';
      case 'ingestion':
      case 'frames extracted':
        return 'bg-status-emeraldBg text-status-emerald border-status-emeraldBorder';
      case 'session_auth':
        return 'bg-blue-50 text-blue-700 border-blue-200';
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200';
    }
  };

  return (
    <section id="view-audit" className="space-y-4 max-w-[1440px] mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 tracking-tight">Chain-of-Custody &amp; Audit Trail</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Immutable compliance ledger recording every case save, inspection, frame override, flag, ingestion, and dossier export.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExportCsv}
            className="px-3 py-1.5 text-xs font-semibold bg-white border border-hairline hover:bg-slate-50 text-slate-700 rounded flex items-center gap-1.5 transition-colors shadow-sm"
          >
            <svg className="w-3.5 h-3.5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            Export Audit CSV
          </button>
          <span className="inline-flex items-center gap-2 font-mono text-[11px] font-medium bg-white border border-hairline rounded px-3 py-1.5 text-status-emerald self-start sm:self-auto">
            <span className="w-2 h-2 rounded-full bg-status-emerald"></span>
            SHA-256 INTEGRITY VERIFIED
          </span>
        </div>
      </div>

      {/* Audit Filters */}
      <div className="bg-white border border-hairline rounded-md p-3.5 flex flex-wrap items-center gap-3">
        <input
          id="auditSearchInput"
          type="text"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Search Investigator, Case/TXN ID, Details, or SHA-256 hash..."
          className="flex-1 min-w-[220px] px-3 py-1.5 text-xs bg-canvas border border-hairline rounded text-slate-900 placeholder-slate-400 focus:outline-none focus:border-steel focus:bg-white font-mono"
        />
        <select
          id="auditActionFilter"
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value)}
          className="px-3 py-1.5 text-xs bg-white border border-hairline rounded text-slate-700 focus:outline-none focus:border-steel"
        >
          <option value="all">Action: All Events</option>
          <option value="SESSION_AUTH">SESSION_AUTH</option>
          <option value="SESSION_END">SESSION_END</option>
          <option value="Save Case">Save Case</option>
          <option value="Inspection">Inspection</option>
          <option value="Frame Override">Frame Override</option>
          <option value="Frame Enhanced">Frame Enhanced</option>
          <option value="Frame Search">Frame Search</option>
          <option value="Frames Extracted">Frames Extracted</option>
          <option value="Flag">Flag</option>
          <option value="Ingestion">Ingestion</option>
          <option value="Dossier Export">Dossier Export</option>
          <option value="Status Update">Status Update</option>
        </select>
      </div>

      {/* Audit Table */}
      <div className="bg-white border border-hairline rounded-md overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-canvas border-b border-hairline text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                <th className="py-2.5 px-4 whitespace-nowrap">Timestamp (IST)</th>
                <th className="py-2.5 px-4">Investigator</th>
                <th className="py-2.5 px-4">Action</th>
                <th className="py-2.5 px-4">Case / TXN ID</th>
                <th className="py-2.5 px-4">Details</th>
                <th className="py-2.5 px-4">SHA-256 Evidence Digest</th>
              </tr>
            </thead>
            <tbody id="auditTableBody" className="divide-y divide-hairline text-xs font-mono">
              {filteredLogs.map((entry, idx) => (
                <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                  <td className="py-2.5 px-4 text-slate-600 whitespace-nowrap">{entry.timestamp}</td>
                  <td className="py-2.5 px-4 font-sans font-medium text-slate-800">{entry.investigator}</td>
                  <td className="py-2.5 px-4">
                    <span className={`text-[10px] font-mono px-2 py-0.5 rounded border uppercase ${getActionBadge(entry.action)}`}>
                      {entry.action}
                    </span>
                  </td>
                  <td className="py-2.5 px-4 text-steel font-semibold">{entry.refId}</td>
                  <td className="py-2.5 px-4 font-sans text-slate-700 max-w-[320px]">{entry.details}</td>
                  <td className="py-2.5 px-4">
                    <div className="flex items-center gap-1.5 text-slate-500">
                      <span className="truncate max-w-[120px]" title={entry.hash}>
                        {entry.hash.substring(0, 16)}...
                      </span>
                      <button
                        onClick={() => handleCopy(entry.hash)}
                        className="p-1 hover:text-slate-900 rounded"
                        title="Copy full SHA-256 hash"
                      >
                        {copiedHash === entry.hash ? (
                          <span className="text-status-emerald font-sans text-[10px]">Copied</span>
                        ) : (
                          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                          </svg>
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {filteredLogs.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-slate-400 font-mono text-xs">
                    No audit records match the current filter.
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
