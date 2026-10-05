import React, { useState } from 'react';
import { ShieldCheck, LogIn, UserPlus, Sparkles, X } from 'lucide-react';
import { loginCompany, registerCompany } from '../api';
import type { UserSession } from '../types';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (session: UserSession) => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose, onSuccess }) => {
  const [isRegister, setIsRegister] = useState(false);
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('demo-logistics');
  const [password, setPassword] = useState('demo1234');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (isRegister) {
        const res = await registerCompany(name, slug, password);
        onSuccess({
          companyId: res.id,
          companyName: res.name,
          slug: res.slug,
          token: res.token,
        });
      } else {
        const res = await loginCompany(slug, password);
        onSuccess({
          companyId: res.id,
          companyName: res.name,
          slug: res.slug,
          token: res.token,
        });
      }
      onClose();
    } catch (err: any) {
      setError(err.message || 'Authentication failed');
    } finally {
      setLoading(false);
    }
  };

  const handleDemoTenant = async () => {
    setError(null);
    setLoading(true);

    try {
      let res;
      try {
        res = await loginCompany('demo-logistics', 'demo1234');
      } catch {
        res = await registerCompany('SF Express Demo Tenant', 'demo-logistics', 'demo1234');
      }
      onSuccess({
        companyId: res.id,
        companyName: res.name,
        slug: res.slug,
        token: res.token,
      });
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to authenticate demo tenant');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-md flex items-center justify-center z-50 p-4">
      <div className="panel max-w-md w-full p-6 relative flex flex-col gap-4 shadow-2xl border border-white/20">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-white transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="text-center">
          <div className="w-12 h-12 rounded-xl bg-cyan-500/20 border border-cyan-500/40 text-cyan-400 flex items-center justify-center mx-auto mb-2">
            <ShieldCheck className="w-6 h-6" />
          </div>
          <h2 className="text-xl font-bold text-white">
            {isRegister ? 'Register Tenant Company' : 'Tenant Security Login'}
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            PostgreSQL RLS Multi-Tenant Authentication Boundary
          </p>
        </div>

        {error && (
          <div className="p-3 rounded-lg bg-rose-500/20 border border-rose-500/40 text-rose-300 text-xs">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          {isRegister && (
            <div>
              <label className="text-xs font-semibold text-slate-300 block mb-1">Company Name</label>
              <input
                type="text"
                placeholder="SF Express Ltd."
                className="input-field text-xs"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>
          )}

          <div>
            <label className="text-xs font-semibold text-slate-300 block mb-1">Tenant Slug</label>
            <input
              type="text"
              placeholder="demo-logistics"
              className="input-field text-xs"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              required
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-300 block mb-1">Password</label>
            <input
              type="password"
              className="input-field text-xs"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn-primary py-2.5 text-xs font-semibold mt-2"
          >
            {isRegister ? (
              <>
                <UserPlus className="w-4 h-4 inline mr-1" />
                Register Company
              </>
            ) : (
              <>
                <LogIn className="w-4 h-4 inline mr-1" />
                Sign In to Tenant Workspace
              </>
            )}
          </button>
        </form>

        <div className="relative my-2 text-center">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-white/10" />
          </div>
          <span className="relative bg-[#0d1527] px-3 text-[10px] text-slate-400 uppercase tracking-wider">
            Or Quick Access
          </span>
        </div>

        <button
          type="button"
          onClick={handleDemoTenant}
          disabled={loading}
          className="btn-secondary py-2.5 text-xs flex items-center justify-center gap-2 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10"
        >
          <Sparkles className="w-4 h-4 text-emerald-400" />
          1-Click SF Express Demo Tenant
        </button>

        <div className="text-center text-xs text-slate-400 mt-2">
          {isRegister ? 'Already registered?' : 'Need a new tenant workspace?'}{' '}
          <button
            onClick={() => setIsRegister(!isRegister)}
            className="text-cyan-400 hover:underline font-semibold"
          >
            {isRegister ? 'Sign In' : 'Create Account'}
          </button>
        </div>
      </div>
    </div>
  );
};
