import React, { useState } from 'react';
import { api } from '@/lib/api';
import { User } from '@/types/forensic';

interface LoginGateProps {
  onLoginSuccess: (user: User) => void;
}

export const LoginGate: React.FC<LoginGateProps> = ({ onLoginSuccess }) => {
  const [email, setEmail] = useState('r.sharma@police.gov.in');
  const [password, setPassword] = useState('strix-forensic-2026');
  const [role, setRole] = useState('Investigator (Case Analyst)');
  const [showPassword, setShowPassword] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorText(null);

    const cleanEmail = email.trim();
    const cleanPwd = password.trim();

    if (!cleanEmail || !cleanPwd) {
      setErrorText('Please enter both Department Email / Badge ID and Password.');
      return;
    }

    setIsLoading(true);
    try {
      const res = await api.login(cleanEmail, cleanPwd);
      onLoginSuccess(res.user);
    } catch (err: any) {
      setErrorText(err.response?.data?.detail || 'Authentication failed. Please verify credentials.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleQuickDemo = (mode: 'investigator' | 'admin') => {
    setErrorText(null);
    if (mode === 'admin') {
      setEmail('admin.forensics@police.gov.in');
      setPassword('strix-admin-2026');
      setRole('System Administrator');
      const adminUser: User = {
        id: 1,
        username: 'admin',
        role: 'admin',
        full_name: 'SysAdmin A. Verma',
        active: true,
        created_at: new Date().toISOString(),
      };
      localStorage.setItem('strix_token', 'demo_admin_jwt');
      localStorage.setItem('strix_user', JSON.stringify(adminUser));
      onLoginSuccess(adminUser);
    } else {
      setEmail('r.sharma@police.gov.in');
      setPassword('strix-forensic-2026');
      setRole('Investigator (Case Analyst)');
      const invUser: User = {
        id: 2,
        username: 'r.sharma',
        role: 'investigator',
        full_name: 'Insp. R. Sharma',
        active: true,
        created_at: new Date().toISOString(),
      };
      localStorage.setItem('strix_token', 'demo_inv_jwt');
      localStorage.setItem('strix_user', JSON.stringify(invUser));
      onLoginSuccess(invUser);
    }
  };

  return (
    <div id="loginGate" className="login-dot-grid fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto">
      <div className="w-full max-w-[440px] bg-white border border-slate-200 rounded-lg shadow-[0_12px_32px_rgba(15,23,42,0.08)] overflow-hidden my-auto">
        <div className="p-6 sm:p-7">
          {/* Top Brand Header */}
          <div className="flex items-center gap-3.5 mb-6">
            <div className="w-11 h-11 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-center shrink-0 shadow-sm">
              {/* Geometric Shield-and-Lens Emblem */}
              <svg
                className="w-6 h-6 text-blue-400"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                <circle cx="12" cy="11" r="2.75"></circle>
                <path d="M12 6.2v1.8M12 14v1.8M7.2 11H9M15 11h1.8"></path>
              </svg>
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold tracking-wide text-slate-900 leading-none">STRIX</h1>
                <span className="font-mono text-[10px] font-semibold px-1.5 py-0.5 rounded bg-steel-tint text-steel border border-steel-border leading-none">
                  PS04
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-1">ATM CCTV Suspect Face Forensics</p>
            </div>
          </div>

          {/* Inline Validation Error Alert */}
          {errorText && (
            <div
              id="loginErrorAlert"
              className="mb-4 px-3 py-2.5 rounded bg-status-crimsonBg border border-status-crimsonBorder text-status-crimson text-xs flex items-center gap-2"
            >
              <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="8" x2="12" y2="12"></line>
                <line x1="12" y1="16" x2="12.01" y2="16"></line>
              </svg>
              <span id="loginErrorText">{errorText}</span>
            </div>
          )}

          {/* Authentication Form */}
          <form id="loginForm" onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div>
              <label htmlFor="loginEmail" className="block text-xs font-semibold text-slate-700 mb-1.5">
                Department Email / Badge ID
              </label>
              <input
                id="loginEmail"
                type="text"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                placeholder="name@police.gov.in or BADGE-ID"
                className="w-full px-3.5 py-2.5 text-sm bg-canvas border border-slate-300 rounded-md text-slate-900 placeholder-slate-400 focus:outline-none focus:bg-white focus:border-steel focus:ring-2 focus:ring-steel/15 transition-colors"
              />
            </div>

            <div>
              <label htmlFor="loginPassword" className="block text-xs font-semibold text-slate-700 mb-1.5">
                Password
              </label>
              <div className="relative">
                <input
                  id="loginPassword"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  placeholder="Enter department password"
                  className="w-full pl-3.5 pr-10 py-2.5 text-sm bg-canvas border border-slate-300 rounded-md text-slate-900 placeholder-slate-400 focus:outline-none focus:bg-white focus:border-steel focus:ring-2 focus:ring-steel/15 transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-700 rounded transition-colors"
                  aria-label="Toggle password visibility"
                  title="Show / Hide Password"
                >
                  {showPassword ? (
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                      <line x1="1" y1="1" x2="23" y2="23"></line>
                    </svg>
                  ) : (
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                      <circle cx="12" cy="11" r="3"></circle>
                    </svg>
                  )}
                </button>
              </div>
            </div>

            <div>
              <label htmlFor="loginRole" className="block text-xs font-semibold text-slate-700 mb-1.5">
                Access Role
              </label>
              <select
                id="loginRole"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full px-3.5 py-2.5 text-sm bg-canvas border border-slate-300 rounded-md text-slate-900 focus:outline-none focus:bg-white focus:border-steel focus:ring-2 focus:ring-steel/15 transition-colors"
              >
                <option value="Investigator (Case Analyst)">Investigator (Case Analyst)</option>
                <option value="Senior Forensic Supervisor">Senior Forensic Supervisor</option>
                <option value="System Administrator">System Administrator</option>
                <option value="Audit & Compliance Officer">Audit & Compliance Officer</option>
              </select>
            </div>

            <button
              id="btnSignInSubmit"
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 px-4 text-sm font-semibold bg-steel hover:bg-steel-hover text-white rounded-md shadow-sm flex items-center justify-center gap-2 transition-colors disabled:opacity-70 disabled:cursor-wait"
            >
              {isLoading && (
                <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3"></circle>
                  <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8v3a5 5 0 00-5 5H4z"></path>
                </svg>
              )}
              <span>{isLoading ? 'Authenticating...' : 'Sign In to Forensic Console'}</span>
            </button>
          </form>

          {/* Quick Demo Access Divider */}
          <div className="relative my-5">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-hairline"></div>
            </div>
            <div className="relative flex justify-center">
              <span className="bg-white px-3 text-[11px] font-medium text-slate-400">Quick Demo Access</span>
            </div>
          </div>

          {/* Two Equal-Width Demo Sign-In Buttons */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <button
              type="button"
              onClick={() => handleQuickDemo('investigator')}
              className="px-3 py-2.5 text-xs font-semibold text-slate-700 bg-canvas hover:bg-slate-100 border border-slate-300 hover:border-slate-400 rounded-md transition-colors text-center leading-snug"
            >
              Demo Sign In (Insp. R. Sharma)
            </button>
            <button
              type="button"
              onClick={() => handleQuickDemo('admin')}
              className="px-3 py-2.5 text-xs font-semibold text-slate-700 bg-canvas hover:bg-slate-100 border border-slate-300 hover:border-slate-400 rounded-md transition-colors text-center leading-snug"
            >
              Admin Sign In
            </button>
          </div>
        </div>

        {/* Card Footer */}
        <div className="px-6 py-3 bg-canvas border-t border-hairline flex items-center justify-between gap-2 text-[11px]">
          <span className="text-slate-500">All sessions logged to Chain of Custody</span>
          <span className="font-mono font-semibold text-steel tracking-wider shrink-0">LOCAL NODE</span>
        </div>
      </div>
    </div>
  );
};
