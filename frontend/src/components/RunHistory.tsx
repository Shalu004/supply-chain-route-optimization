import React from 'react';
import { History, Clock, Route, DollarSign, ArrowUpRight } from 'lucide-react';
import type { RunHistoryItem } from '../types';

interface RunHistoryProps {
  history: RunHistoryItem[];
  onSelectRun: (run: RunHistoryItem) => void;
}

export const RunHistory: React.FC<RunHistoryProps> = ({ history, onSelectRun }) => {
  return (
    <div className="panel p-6 flex-1 flex flex-col max-w-5xl mx-auto w-full my-6 overflow-hidden">
      <div className="flex justify-between items-center mb-6 pb-3 border-b border-white/10">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <History className="w-6 h-6 text-cyan-400" />
            Optimization Run History
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Persisted optimization execution logs and tenant route history.
          </p>
        </div>
        <div className="text-xs text-slate-400">
          Total Executions: <span className="text-white font-bold">{history.length}</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-3 pr-2">
        {history.length === 0 ? (
          <div className="text-center py-16 text-slate-500 border border-dashed border-white/10 rounded-xl">
            <History className="w-12 h-12 mx-auto mb-3 text-slate-600 animate-pulse" />
            <p className="text-sm font-semibold">No run history found.</p>
            <p className="text-xs text-slate-500 mt-1">
              Run a route optimization in the Route Studio to record metrics here.
            </p>
          </div>
        ) : (
          history.map((item) => (
            <div
              key={item.id}
              className="p-4 rounded-xl bg-white/5 border border-white/10 hover:border-cyan-500/40 transition-all flex items-center justify-between text-sm"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="badge badge-primary text-xs uppercase">{item.solver_type}</span>
                  <span className="badge bg-purple-500/20 text-purple-300 border border-purple-500/30 text-xs">
                    {item.distance_provider}
                  </span>
                  <span className="text-xs text-slate-400 flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5 text-slate-400" />
                    {new Date(item.created_at).toLocaleString()}
                  </span>
                </div>
                <div className="text-xs text-slate-400">Run ID: {item.id}</div>
              </div>

              <div className="flex items-center gap-6">
                <div className="text-right">
                  <div className="text-xs text-slate-400 flex items-center justify-end gap-1">
                    <Route className="w-3.5 h-3.5 text-cyan-400" /> Total Distance
                  </div>
                  <div className="font-bold text-white">{item.total_distance_km.toFixed(2)} km</div>
                </div>

                <div className="text-right">
                  <div className="text-xs text-slate-400 flex items-center justify-end gap-1">
                    <DollarSign className="w-3.5 h-3.5 text-emerald-400" /> Total Cost
                  </div>
                  <div className="font-bold text-emerald-400">${item.total_cost.toFixed(2)}</div>
                </div>

                <button
                  onClick={() => onSelectRun(item)}
                  className="btn-secondary text-xs py-2 px-3 flex items-center gap-1.5"
                >
                  Inspect
                  <ArrowUpRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
