import React, { useState } from 'react';
import { User } from '@/types/forensic';
import { MockCase } from '@/lib/mockData';

interface AppShellProps {
  user: User;
  currentView: string;
  onNavigate: (view: string) => void;
  activeCase: MockCase;
  txnCount: number;
  auditCount: number;
  onSignOut: () => void;
  onSaveCase: () => void;
  onRunFullDemo: () => void;
  children: React.ReactNode;
}

export const AppShell: React.FC<AppShellProps> = ({
  user,
  currentView,
  onNavigate,
  activeCase,
  txnCount,
  auditCount,
  onSignOut,
  onSaveCase,
  onRunFullDemo,
  children,
}) => {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map((part) => part[0])
      .filter(Boolean)
      .slice(0, 2)
      .join('')
      .toUpperCase();
  };

  const getViewTitle = (v: string) => {
    switch (v) {
      case 'dashboard':
        return 'Dashboard';
      case 'transactions':
        return 'Transactions';
      case 'inspector':
        return `Case Inspector / ${activeCase.caseId}`;
      case 'ingest':
        return 'Ingest Footage';
      case 'audit':
        return 'Audit Trail';
      default:
        return 'Dashboard';
    }
  };

  return (
    <div id="appShell" className="h-screen w-full overflow-hidden flex flex-col md:flex-row">
      {/* Mobile Sidebar Backdrop */}
      {mobileSidebarOpen && (
        <div
          id="mobileBackdrop"
          className="fixed inset-0 bg-slate-900/50 z-30 md:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* Fixed Left Sidebar (240px) */}
      <aside
        id="sidebar"
        className={`fixed md:static inset-y-0 left-0 z-40 w-[240px] shrink-0 bg-sidebar text-slate-300 flex flex-col border-r border-slate-800 transform ${
          mobileSidebarOpen ? 'translate-x-0' : '-translate-x-full'
        } md:translate-x-0 transition-transform duration-150`}
      >
        {/* Strix Brand Emblem & Title */}
        <div className="h-14 px-4 flex items-center gap-3 border-b border-slate-800 shrink-0">
          <div className="w-8 h-8 rounded bg-steel/20 border border-steel-light/40 flex items-center justify-center shrink-0">
            <svg
              className="w-4 h-4 text-blue-400"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
              <circle cx="12" cy="11" r="2.5"></circle>
              <path d="M12 6.5v2M12 13.5v2M7.5 11h2M14.5 11h2"></path>
            </svg>
          </div>
          <div className="leading-tight min-w-0">
            <div className="text-white font-semibold text-sm tracking-wide truncate">STRIX</div>
            <div className="text-[11px] font-mono text-slate-400 truncate">ATM Video Forensics</div>
          </div>
        </div>

        {/* Primary Navigation */}
        <nav className="flex-1 py-4 space-y-0.5 text-[13px] font-medium overflow-y-auto">
          <div className="px-4 pb-1.5 text-[10px] font-mono uppercase tracking-wider text-slate-500">Workspace</div>

          <button
            id="nav-dashboard"
            onClick={() => {
              onNavigate('dashboard');
              setMobileSidebarOpen(false);
            }}
            className={`nav-btn w-full flex items-center gap-3 px-4 py-2.5 text-left ${
              currentView === 'dashboard' ? 'active' : ''
            }`}
          >
            <svg className="w-4 h-4 shrink-0 opacity-85" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <rect x="3" y="3" width="7" height="7" rx="1"></rect>
              <rect x="14" y="3" width="7" height="7" rx="1"></rect>
              <rect x="14" y="14" width="7" height="7" rx="1"></rect>
              <rect x="3" y="14" width="7" height="7" rx="1"></rect>
            </svg>
            <span>Dashboard</span>
          </button>

          <button
            id="nav-transactions"
            onClick={() => {
              onNavigate('transactions');
              setMobileSidebarOpen(false);
            }}
            className={`nav-btn w-full flex items-center gap-3 px-4 py-2.5 text-left ${
              currentView === 'transactions' ? 'active' : ''
            }`}
          >
            <svg className="w-4 h-4 shrink-0 opacity-85" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M3 6h18M3 12h18M3 18h18"></path>
            </svg>
            <span>Transactions</span>
            <span
              id="navTxnCount"
              className="ml-auto font-mono text-[11px] bg-slate-800 text-slate-300 border border-slate-700 px-1.5 py-0.5 rounded tabular-nums"
            >
              {txnCount}
            </span>
          </button>

          <button
            id="nav-inspector"
            onClick={() => {
              onNavigate('inspector');
              setMobileSidebarOpen(false);
            }}
            className={`nav-btn w-full flex items-center gap-3 px-4 py-2.5 text-left ${
              currentView === 'inspector' ? 'active' : ''
            }`}
          >
            <svg className="w-4 h-4 shrink-0 opacity-85" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <rect x="2" y="4" width="20" height="14" rx="2"></rect>
              <path d="M8 21h8M12 18v3"></path>
              <circle cx="12" cy="11" r="2.5"></circle>
            </svg>
            <span>Case Inspector</span>
          </button>

          <button
            id="nav-ingest"
            onClick={() => {
              onNavigate('ingest');
              setMobileSidebarOpen(false);
            }}
            className={`nav-btn w-full flex items-center gap-3 px-4 py-2.5 text-left ${
              currentView === 'ingest' ? 'active' : ''
            }`}
          >
            <svg className="w-4 h-4 shrink-0 opacity-85" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
            <span>Ingest Footage</span>
          </button>

          <div className="pt-5 px-4 pb-1.5 text-[10px] font-mono uppercase tracking-wider text-slate-500">Compliance</div>

          <button
            id="nav-audit"
            onClick={() => {
              onNavigate('audit');
              setMobileSidebarOpen(false);
            }}
            className={`nav-btn w-full flex items-center gap-3 px-4 py-2.5 text-left ${
              currentView === 'audit' ? 'active' : ''
            }`}
          >
            <svg className="w-4 h-4 shrink-0 opacity-85" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
              <path d="M9 12l2 2 4-4"></path>
            </svg>
            <span>Audit Trail</span>
            <span id="navAuditCount" className="ml-auto font-mono text-[11px] text-slate-400 tabular-nums">
              {auditCount}
            </span>
          </button>
        </nav>

        {/* Authorized Investigator & Node Footer */}
        <div className="p-4 border-t border-slate-800 space-y-3 shrink-0">
          <div className="flex items-center gap-2.5">
            <div
              id="sidebarUserInitials"
              className="w-8 h-8 rounded bg-slate-800 border border-slate-700 text-slate-200 text-xs font-semibold flex items-center justify-center shrink-0"
            >
              {getInitials(user.full_name || user.username)}
            </div>
            <div className="min-w-0 leading-tight">
              <div id="sidebarUserName" className="text-xs font-semibold text-white truncate">
                {user.full_name || user.username}
              </div>
              <div id="sidebarUserEmail" className="text-[11px] font-mono text-slate-400 truncate">
                {user.username.includes('@') ? user.username : `${user.username}@police.gov.in`}
              </div>
            </div>
          </div>
          <div
            id="sidebarUserRole"
            className="text-[10px] font-mono px-2 py-1 rounded bg-slate-800/90 border border-slate-700 text-blue-300 truncate"
          >
            {user.role === 'admin' ? 'System Administrator' : 'Investigator (Case Analyst)'}
          </div>
          <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-slate-400">
            <span className="flex items-center gap-1.5 text-emerald-400">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> LOCAL NODE
            </span>
            <button
              onClick={onSignOut}
              className="text-slate-300 hover:text-white hover:underline font-sans text-[11px] font-medium flex items-center gap-1 transition-colors"
            >
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                <polyline points="16 17 21 12 16 7"></polyline>
                <line x1="21" y1="12" x2="9" y2="12"></line>
              </svg>
              Sign Out
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Shell */}
      <div className="flex-1 flex flex-col min-w-0 h-screen overflow-hidden">
        {/* Sticky Top Context Header Bar */}
        <header className="sticky top-0 z-20 h-14 bg-white border-b border-hairline px-4 md:px-6 flex items-center justify-between gap-3 shrink-0">
          {/* Left: Mobile Trigger + Breadcrumb */}
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={() => setMobileSidebarOpen(true)}
              className="md:hidden p-1.5 rounded border border-hairline text-slate-600 hover:bg-slate-50"
              aria-label="Open navigation"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 12h18M3 6h18M3 18h18"></path>
              </svg>
            </button>

            <div className="flex items-center gap-2 text-sm truncate">
              <span className="text-slate-500 font-medium hidden sm:inline">Strix</span>
              <span className="text-slate-300 hidden sm:inline">/</span>
              <span id="headerBreadcrumb" className="font-semibold text-slate-900 truncate">
                {getViewTitle(currentView)}
              </span>
            </div>
          </div>

          {/* Right: Active Case Pill, Save Case, Run Full Demo */}
          <div className="flex items-center gap-2 sm:gap-2.5 shrink-0">
            {/* Active Case Pill */}
            <button
              onClick={() => onNavigate('inspector')}
              title="Open active case in Case Inspector"
              className="hidden lg:flex items-center gap-2 px-2.5 py-1.5 rounded border border-hairline bg-canvas hover:border-slate-300 transition-colors text-xs"
            >
              <svg className="w-3.5 h-3.5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
              </svg>
              <span id="headerActiveCaseId" className="font-mono font-semibold text-slate-800">
                {activeCase.caseId}
              </span>
              <span className="h-3.5 w-px bg-hairline"></span>
              <span
                id="headerActiveCaseStatus"
                className="inline-flex items-center gap-1.5 font-mono text-[11px] font-medium text-status-emerald"
              >
                <span id="headerStatusDot" className="w-1.5 h-1.5 rounded-full bg-status-emerald"></span>
                <span id="headerStatusText">{activeCase.status.toUpperCase()}</span>
              </span>
            </button>

            {/* Save Case Button */}
            <button
              onClick={onSaveCase}
              className="px-3 py-1.5 text-xs font-medium bg-white border border-hairline hover:bg-slate-50 text-slate-700 rounded flex items-center gap-1.5 transition-colors"
            >
              <svg className="w-3.5 h-3.5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
                <polyline points="17 21 17 13 7 13 7 21"></polyline>
                <polyline points="7 3 7 8 15 8"></polyline>
              </svg>
              <span className="hidden sm:inline">Save Case</span>
            </button>

            {/* Run Full Demo Primary Button */}
            <button
              onClick={onRunFullDemo}
              className="px-3.5 py-1.5 text-xs font-semibold bg-steel hover:bg-steel-hover text-white rounded flex items-center gap-1.5 transition-colors shadow-sm"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
              </svg>
              <span>Run Full Demo</span>
            </button>
          </div>
        </header>

        {/* Scrollable Workspace */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
};
