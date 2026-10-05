import React from 'react';
import { Route, Gauge, DollarSign, Clock, AlertTriangle, CheckCircle2 } from 'lucide-react';
import type { OptimizeResponse } from '../types';

interface MetricsDashboardProps {
  response: OptimizeResponse | null;
}

export const MetricsDashboard: React.FC<MetricsDashboardProps> = ({ response }) => {
  if (!response) {
    return (
      <aside className="panel sidebar-right flex flex-col items-center justify-center text-center text-slate-500 p-6">
        <Gauge className="w-12 h-12 text-slate-600 mb-3 animate-pulse" />
        <h3 className="text-sm font-semibold text-slate-400">No Optimization Run Active</h3>
        <p className="text-xs text-slate-500 mt-1 max-w-xs">
          Configure delivery locations and run the solver to inspect real-time metrics, fuel efficiency, and route breakdowns.
        </p>
      </aside>
    );
  }

  const { total_distance_km, total_cost, execution_time_seconds, routes, unassigned, solver_used } = response;

  return (
    <aside className="panel sidebar-right flex flex-col gap-4 overflow-y-auto">
      <div className="pb-2 border-b border-white/10 flex justify-between items-center">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Gauge className="w-5 h-5 text-emerald-400" />
            Optimization Metrics
          </h2>
          <p className="text-xs text-slate-400">Engine: {solver_used}</p>
        </div>
        <span className="badge badge-success text-xs font-medium">SUCCESS</span>
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        <div className="kpi-card">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span className="text-xs">Total Distance</span>
            <Route className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-xl font-bold text-white">
            {total_distance_km.toFixed(2)} <span className="text-xs font-normal text-slate-400">km</span>
          </div>
        </div>

        <div className="kpi-card">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span className="text-xs">Est. Operational Cost</span>
            <DollarSign className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-xl font-bold text-emerald-400">
            ${total_cost.toFixed(2)}
          </div>
        </div>

        <div className="kpi-card">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span className="text-xs">Active Dispatch</span>
            <CheckCircle2 className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-xl font-bold text-white">
            {routes.length} <span className="text-xs font-normal text-slate-400">vehicles</span>
          </div>
        </div>

        <div className="kpi-card">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span className="text-xs">Solver Time</span>
            <Clock className="w-4 h-4 text-purple-400" />
          </div>
          <div className="text-xl font-bold text-white">
            {execution_time_seconds.toFixed(3)} <span className="text-xs font-normal text-slate-400">s</span>
          </div>
        </div>
      </div>

      {unassigned && unassigned.length > 0 && (
        <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold">{unassigned.length} Unassigned Stops</div>
            <div className="text-amber-200/80">Vehicle capacity constraints exceeded. Additional fleet required.</div>
          </div>
        </div>
      )}

      <div className="flex-1 flex flex-col min-h-0">
        <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-2">
          Assigned Route Schedules ({routes.length})
        </h3>

        <div className="space-y-3 overflow-y-auto pr-1 flex-1">
          {routes.map((rt, idx) => (
            <div
              key={rt.vehicle_id || idx}
              className="p-3 rounded-lg bg-white/5 border border-white/10 hover:border-cyan-500/30 transition-all text-xs"
            >
              <div className="flex justify-between items-center mb-1.5 pb-1 border-b border-white/5">
                <span className="font-bold text-cyan-300">
                  {rt.vehicle_name || 'Vehicle ' + rt.vehicle_id}
                </span>
                <div className="flex gap-2 text-slate-400">
                  <span>{rt.distance_km.toFixed(1)} km</span>
                  <span>?</span>
                  <span className="text-emerald-400">${rt.cost.toFixed(2)}</span>
                </div>
              </div>

              <div className="space-y-1 pl-2 border-l border-cyan-500/30">
                <div className="text-slate-400 font-medium flex justify-between">
                  <span>?? Depot Start</span>
                </div>
                {rt.route.map((step, sIdx) => (
                  <div key={sIdx} className="flex justify-between text-slate-300 pl-2">
                    <span>
                      {sIdx + 1}. <strong className="text-white">{step.stop_id}</strong>
                    </span>
                    <span className="text-slate-400">Demand: {step.demand}</span>
                  </div>
                ))}
                <div className="text-slate-400 font-medium flex justify-between">
                  <span>?? Depot Return</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
};
