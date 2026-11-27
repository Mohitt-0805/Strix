import React, { useState, useEffect, useRef } from 'react';
import { MockCase } from '@/lib/mockData';
import { drawForensicFace } from '@/lib/forensicCanvas';

interface TransactionsViewProps {
  cases: MockCase[];
  onOpenCase: (caseObj: MockCase) => void;
  onNavigate: (view: string) => void;
}

export const TransactionsView: React.FC<TransactionsViewProps> = ({ cases, onOpenCase, onNavigate }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [minIqa, setMinIqa] = useState(0);
  const [conditionFilter, setConditionFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');

  const filteredCases = cases.filter((c) => {
    const q = searchTerm.toLowerCase();
    const matchesSearch =
      c.caseId.toLowerCase().includes(q) ||
      c.txnId.toLowerCase().includes(q) ||
      c.atmId.toLowerCase().includes(q) ||
      c.location.toLowerCase().includes(q) ||
      c.cardLast4.includes(q);

    const matchesIqa = c.quality >= minIqa;
    const matchesCondition =
      conditionFilter === 'all' || c.conditions.some((cond) => cond.toLowerCase().includes(conditionFilter.toLowerCase()));
    const matchesStatus = statusFilter === 'all' || c.status === statusFilter;

    return matchesSearch && matchesIqa && matchesCondition && matchesStatus;
  });

  const resetFilters = () => {
    setSearchTerm('');
    setMinIqa(0);
    setConditionFilter('all');
    setStatusFilter('all');
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'Verified':
        return 'bg-status-emeraldBg text-status-emerald border-status-emeraldBorder';
      case 'Pending Review':
        return 'bg-status-amberBg text-status-amber border-status-amberBorder';
      case 'In Progress':
        return 'bg-steel-tint text-steel border-steel-border';
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200';
    }
  };

  return (
    <section id="view-transactions" className="space-y-4 max-w-[1440px] mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 tracking-tight">ATM Cash Withdrawal Transactions</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Search indexed ATM CCTV facial extractions synchronized with cardholder withdrawal logs.
          </p>
        </div>
        <button
          onClick={() => onNavigate('ingest')}
          className="px-3.5 py-1.5 text-xs font-semibold bg-steel hover:bg-steel-hover text-white rounded flex items-center gap-1.5 transition-colors self-start sm:self-auto"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          Ingest Footage
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
            placeholder="Search Transaction ID, Terminal ID, Card Last-4..."
            className="w-full pl-8 pr-3 py-1.5 text-xs bg-canvas border border-hairline rounded text-slate-900 placeholder-slate-400 focus:outline-none focus:border-steel focus:bg-white"
          />
        </div>

        {/* Min IQA Slider (0-100) */}
        <div className="flex items-center gap-2.5 px-3 py-1.5 bg-canvas border border-hairline rounded min-w-[200px]">
          <span className="text-[11px] font-medium text-slate-600 whitespace-nowrap">Min IQA:</span>
          <input
            id="txnMinIqaSlider"
            type="range"
            min="0"
            max="100"
            value={minIqa}
            onChange={(e) => setMinIqa(Number(e.target.value))}
            className="forensic-slider w-24"
          />
          <span id="txnMinIqaVal" className="font-mono text-xs font-semibold text-steel tabular-nums w-6 text-right">
            {minIqa}
          </span>
        </div>

        {/* Environmental Condition Filter */}
        <select
          id="txnConditionFilter"
          value={conditionFilter}
          onChange={(e) => setConditionFilter(e.target.value)}
          className="px-2.5 py-1.5 text-xs bg-white border border-hairline rounded text-slate-700 focus:outline-none focus:border-steel"
        >
          <option value="all">Condition: All</option>
          <option value="Low-Light">Low-Light</option>
          <option value="Partial Occlusion">Partial Occlusion</option>
          <option value="Off-Angle">Off-Angle</option>
          <option value="Motion Blur">Motion Blur</option>
          <option value="Backlit">Backlit</option>
          <option value="Clear">Clear</option>
        </select>

        {/* Status Filter */}
        <select
          id="txnStatusFilter"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-2.5 py-1.5 text-xs bg-white border border-hairline rounded text-slate-700 focus:outline-none focus:border-steel"
        >
          <option value="all">Status: All</option>
          <option value="In Progress">In Progress</option>
          <option value="Pending Review">Pending Review</option>
          <option value="Verified">Verified</option>
          <option value="Flagged">Flagged</option>
          <option value="Archived">Archived</option>
        </select>

        <button
          onClick={resetFilters}
          className="px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded transition-colors"
        >
          Reset
        </button>
      </div>

      {/* High-Density Transactions Table */}
      <div className="bg-white border border-hairline rounded-md overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-canvas border-b border-hairline text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                <th className="py-2.5 px-4 w-14">Face</th>
                <th className="py-2.5 px-4">Case & TXN ID</th>
                <th className="py-2.5 px-4">Terminal & Camera</th>
                <th className="py-2.5 px-4">Timestamp (IST)</th>
                <th className="py-2.5 px-4">Withdrawal Amount</th>
                <th className="py-2.5 px-4">Composite IQA</th>
                <th className="py-2.5 px-4">Quality Conditions</th>
                <th className="py-2.5 px-4">Status</th>
                <th className="py-2.5 px-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody id="transactionsTableBody" className="divide-y divide-hairline text-xs">
              {filteredCases.map((c) => (
                <TransactionRow key={c.caseId} caseItem={c} onOpenCase={onOpenCase} getStatusBadge={getStatusBadge} />
              ))}
              {filteredCases.length === 0 && (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-slate-400 font-mono text-xs">
                    No transactions match the selected filters.
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

interface TransactionRowProps {
  caseItem: MockCase;
  onOpenCase: (caseObj: MockCase) => void;
  getStatusBadge: (status: string) => string;
}

const TransactionRow: React.FC<TransactionRowProps> = ({ caseItem, onOpenCase, getStatusBadge }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (canvasRef.current && caseItem.candidates.length > 0) {
      const cand = caseItem.candidates[caseItem.primaryCandidateIdx || 0];
      drawForensicFace(canvasRef.current, caseItem.faceProfile, {
        isRaw: false,
        yaw: cand.yaw,
        pitch: cand.pitch,
        blur: cand.blur,
        dark: cand.dark,
        glare: cand.glare,
        handOcc: cand.handOcc,
      });
    }
  }, [caseItem]);

  return (
    <tr className="hover:bg-slate-50/80 transition-colors">
      <td className="py-2.5 px-4">
        <div className="w-10 h-10 rounded border border-hairline overflow-hidden bg-[#11161E] shrink-0">
          <canvas ref={canvasRef} width={48} height={48} className="w-full h-full block" />
        </div>
      </td>
      <td className="py-2.5 px-4">
        <div className="font-mono font-semibold text-slate-900">{caseItem.caseId}</div>
        <div className="font-mono text-[11px] text-steel">{caseItem.txnId}</div>
      </td>
      <td className="py-2.5 px-4">
        <div className="font-mono font-medium text-slate-800">{caseItem.atmId}</div>
        <div className="text-[11px] text-slate-500 truncate max-w-[180px]">{caseItem.camera}</div>
      </td>
      <td className="py-2.5 px-4 font-mono text-slate-600 whitespace-nowrap">{caseItem.timestamp}</td>
      <td className="py-2.5 px-4">
        <div className="font-mono font-semibold text-slate-900 tabular-nums">{caseItem.amount}</div>
        <div className="font-mono text-[11px] text-slate-400">•••• {caseItem.cardLast4}</div>
      </td>
      <td className="py-2.5 px-4">
        <div className="flex items-center gap-2">
          <span className="font-mono font-semibold text-slate-900 tabular-nums">{caseItem.quality}</span>
          <div className="w-16 h-1.5 bg-slate-100 rounded-full overflow-hidden">
            <div
              className={`h-full ${
                caseItem.quality >= 85
                  ? 'bg-status-emerald'
                  : caseItem.quality >= 70
                  ? 'bg-status-amber'
                  : 'bg-status-crimson'
              }`}
              style={{ width: `${caseItem.quality}%` }}
            ></div>
          </div>
        </div>
      </td>
      <td className="py-2.5 px-4">
        <div className="flex flex-wrap gap-1">
          {caseItem.conditions.map((cond, idx) => (
            <span
              key={idx}
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200"
            >
              {cond}
            </span>
          ))}
        </div>
      </td>
      <td className="py-2.5 px-4">
        <span className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded border ${getStatusBadge(caseItem.status)}`}>
          {caseItem.status}
        </span>
      </td>
      <td className="py-2.5 px-4 text-right">
        <button
          onClick={() => onOpenCase(caseItem)}
          className="px-2.5 py-1 text-xs font-medium text-steel bg-steel-tint hover:bg-steel hover:text-white border border-steel-border rounded transition-colors"
        >
          Inspect Evidence
        </button>
      </td>
    </tr>
  );
};
