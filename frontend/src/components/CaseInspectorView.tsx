import React from 'react';
import { RunResult, ClipOut, PublicConfig } from '@/types/forensic';
import { RunInspectorView } from './RunInspectorView';

export interface CaseInspectorViewProps {
  runResult: RunResult | null;
  clip: ClipOut | null;
  publicConfig: PublicConfig | null;
  onAuditAction: (action: string, refId: string, details: string) => void;
  onNavigate: (view: string) => void;
}

export const CaseInspectorView: React.FC<CaseInspectorViewProps> = (props) => {
  if (!props.runResult && !props.clip) {
    return (
      <div id="view-case-inspector-empty" className="max-w-[1440px] mx-auto py-12 text-center space-y-4">
        <div className="w-16 h-16 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-400">
          <svg className="w-8 h-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <rect x="2" y="4" width="20" height="14" rx="2"></rect>
            <path d="M8 21h8M12 18v3"></path>
            <circle cx="12" cy="11" r="2.5"></circle>
          </svg>
        </div>
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-slate-800">Select a case from Transactions</h2>
          <p className="text-xs text-slate-500 max-w-sm mx-auto">
            Choose an indexed surveillance clip from the footage ledger to review candidate face crops and execute forensic analysis.
          </p>
        </div>
        <div>
          <button
            onClick={() => props.onNavigate('transactions')}
            className="px-4 py-2 text-xs font-semibold bg-steel hover:bg-steel-hover text-white rounded transition-colors shadow-sm"
          >
            Go to Clips &amp; Footage &rarr;
          </button>
        </div>
      </div>
    );
  }

  return <RunInspectorView {...props} />;
};

export default CaseInspectorView;
