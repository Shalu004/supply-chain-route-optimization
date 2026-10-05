import React from 'react';
import { Truck, Map, ShieldCheck, History, LogIn, LogOut } from 'lucide-react';
import type { UserSession } from '../types';

interface NavbarProps {
  activeTab: 'studio' | 'fleet' | 'history';
  setActiveTab: (tab: 'studio' | 'fleet' | 'history') => void;
  session: UserSession | null;
  onOpenAuth: () => void;
  onLogout: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  session,
  onOpenAuth,
  onLogout,
}) => {
  return (
    <header className="navbar">
      <div className="navbar-brand">
        <div className="navbar-logo">
          <Truck className="w-6 h-6 text-cyan-400" />
        </div>
        <div>
          <h1 className="navbar-title">RouteOpt</h1>
          <p className="navbar-subtitle">Enterprise Supply Chain Studio</p>
        </div>
      </div>

      <nav className="navbar-nav">
        <button
          className={activeTab === 'studio' ? 'nav-btn active' : 'nav-btn'}
          onClick={() => setActiveTab('studio')}
        >
          <Map className="w-4 h-4" />
          <span>Route Studio</span>
        </button>

        <button
          className={activeTab === 'fleet' ? 'nav-btn active' : 'nav-btn'}
          onClick={() => setActiveTab('fleet')}
        >
          <Truck className="w-4 h-4" />
          <span>Fleet Manager</span>
        </button>

        <button
          className={activeTab === 'history' ? 'nav-btn active' : 'nav-btn'}
          onClick={() => setActiveTab('history')}
        >
          <History className="w-4 h-4" />
          <span>Optimization History</span>
        </button>
      </nav>

      <div className="navbar-actions">
        {session ? (
          <div className="flex items-center gap-3">
            <div className="tenant-badge">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <span>{session.companyName}</span>
            </div>
            <button className="btn-secondary py-1.5 px-3 text-xs" onClick={onLogout}>
              <LogOut className="w-3.5 h-3.5 inline mr-1" />
              Sign Out
            </button>
          </div>
        ) : (
          <button className="btn-primary py-1.5 px-4 text-sm" onClick={onOpenAuth}>
            <LogIn className="w-4 h-4 inline mr-1.5" />
            Tenant Sign In
          </button>
        )}
      </div>
    </header>
  );
};
