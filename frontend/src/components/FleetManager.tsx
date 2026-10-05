import React, { useState } from 'react';
import { Truck, Plus, Trash2, Fuel, DollarSign, Gauge } from 'lucide-react';
import type { Vehicle } from '../types';

interface FleetManagerProps {
  vehicles: Vehicle[];
  onCreateVehicle: (data: Omit<Vehicle, 'id' | 'company_id' | 'created_at'>) => void;
  onDeleteVehicle: (id: string) => void;
  isLoading: boolean;
}

export const FleetManager: React.FC<FleetManagerProps> = ({
  vehicles,
  onCreateVehicle,
  onDeleteVehicle,
  isLoading,
}) => {
  const [name, setName] = useState('');
  const [capacity, setCapacity] = useState('100');
  const [fixedCost, setFixedCost] = useState('50.0');
  const [costPerKm, setCostPerKm] = useState('1.5');
  const [maxDistance, setMaxDistance] = useState('300');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name) return;

    onCreateVehicle({
      name,
      capacity: parseInt(capacity, 10) || 100,
      fixed_cost: parseFloat(fixedCost) || 50.0,
      cost_per_km: parseFloat(costPerKm) || 1.5,
      max_route_distance_km: maxDistance ? parseFloat(maxDistance) : null,
      status: 'active',
    });

    setName('');
  };

  return (
    <div className="panel p-6 flex-1 flex flex-col max-w-6xl mx-auto w-full my-6 overflow-hidden">
      <div className="flex justify-between items-center mb-6 pb-3 border-b border-white/10">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Truck className="w-6 h-6 text-cyan-400" />
            Heterogeneous Fleet Management
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Configure vehicle specs, capacities, fixed operational costs, and maximum route distance constraints.
          </p>
        </div>
        <div className="text-xs text-slate-400">
          Total Vehicles: <span className="text-white font-bold">{vehicles.length}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0">
        <form onSubmit={handleSubmit} className="p-4 rounded-xl bg-white/5 border border-white/10 flex flex-col gap-3">
          <h3 className="text-sm font-bold text-slate-200 flex items-center gap-1.5 uppercase tracking-wider">
            <Plus className="w-4 h-4 text-cyan-400" /> Register Vehicle
          </h3>

          <div>
            <label className="text-xs text-slate-300 font-semibold mb-1 block">Vehicle Name / Label</label>
            <input
              type="text"
              placeholder="e.g. Heavy Duty Semi #10"
              className="input-field text-xs"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-slate-300 font-semibold mb-1 block">Capacity (Units)</label>
              <input
                type="number"
                className="input-field text-xs"
                value={capacity}
                onChange={(e) => setCapacity(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-slate-300 font-semibold mb-1 block">Fixed Dispatch ($)</label>
              <input
                type="number"
                step="0.1"
                className="input-field text-xs"
                value={fixedCost}
                onChange={(e) => setFixedCost(e.target.value)}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-slate-300 font-semibold mb-1 block">Cost / km ($)</label>
              <input
                type="number"
                step="0.1"
                className="input-field text-xs"
                value={costPerKm}
                onChange={(e) => setCostPerKm(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-slate-300 font-semibold mb-1 block">Max Dist (km)</label>
              <input
                type="number"
                placeholder="Optional"
                className="input-field text-xs"
                value={maxDistance}
                onChange={(e) => setMaxDistance(e.target.value)}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="btn-primary py-2.5 text-xs font-semibold mt-2"
          >
            + Add Vehicle to Fleet
          </button>
        </form>

        <div className="lg:col-span-2 overflow-y-auto pr-2 space-y-3">
          {vehicles.length === 0 ? (
            <div className="text-center py-16 text-slate-500 border border-dashed border-white/10 rounded-xl">
              <Truck className="w-12 h-12 mx-auto mb-3 text-slate-600 animate-pulse" />
              <p className="text-sm font-semibold">No active vehicles registered.</p>
              <p className="text-xs text-slate-500 mt-1">Add vehicles using the form to configure route capacity.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {vehicles.map((v) => (
                <div
                  key={v.id}
                  className="p-4 rounded-xl bg-white/5 border border-white/10 hover:border-cyan-500/30 transition-all flex flex-col justify-between"
                >
                  <div className="flex justify-between items-start mb-2">
                    <div>
                      <h4 className="font-bold text-cyan-300 text-sm">{v.name}</h4>
                      <span className="badge badge-success text-[10px] uppercase mt-0.5">{v.status}</span>
                    </div>
                    <button
                      onClick={() => onDeleteVehicle(v.id)}
                      className="text-slate-500 hover:text-rose-400 p-1 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-xs text-slate-300 mt-2 pt-2 border-t border-white/5">
                    <div className="flex items-center gap-1.5">
                      <Gauge className="w-3.5 h-3.5 text-cyan-400" />
                      <span>Cap: <strong>{v.capacity}</strong></span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Fixed: <strong>${v.fixed_cost}</strong></span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Fuel className="w-3.5 h-3.5 text-amber-400" />
                      <span>Cost/km: <strong>${v.cost_per_km}</strong></span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Truck className="w-3.5 h-3.5 text-purple-400" />
                      <span>Max: <strong>{v.max_route_distance_km ? v.max_route_distance_km + ' km' : '?'}</strong></span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
