import React, { useState } from 'react';
import { Play, Sparkles, MapPin, Zap, RefreshCw } from 'lucide-react';
import type { StopInput, OptimizeRequest } from '../types';

interface OptimizationFormProps {
  onOptimize: (req: OptimizeRequest) => void;
  isLoading: boolean;
  companyId: string;

  stops: StopInput[];
  setStops: React.Dispatch<React.SetStateAction<StopInput[]>>;
  depot: [number, number];
  setDepot: (loc: [number, number]) => void;
  solverType: 'ortools' | 'heuristic';
  setSolverType: (st: 'ortools' | 'heuristic') => void;
  distanceProvider: 'osrm' | 'haversine';
  setDistanceProvider: (dp: 'osrm' | 'haversine') => void;
}

export const OptimizationForm: React.FC<OptimizationFormProps> = ({
  onOptimize,
  isLoading,
  companyId,
  stops,
  setStops,
  depot,
  setDepot,
  solverType,
  setSolverType,
  distanceProvider,
  setDistanceProvider,
}) => {
  const [newStopLat, setNewStopLat] = useState('37.7700');
  const [newStopLng, setNewStopLng] = useState('-122.4200');
  const [newStopDemand, setNewStopDemand] = useState('15');

  const handleAddStop = (e: React.FormEvent) => {
    e.preventDefault();
    const lat = parseFloat(newStopLat);
    const lng = parseFloat(newStopLng);
    const dem = parseInt(newStopDemand, 10);

    if (isNaN(lat) || isNaN(lng) || isNaN(dem)) return;

    const newStop: StopInput = {
      stop_id: 'stop-' + (stops.length + 1),
      location: [lat, lng],
      demand: dem,
    };

    setStops([...stops, newStop]);
  };

  const handleLoadSampleData = () => {
    setDepot([37.7749, -122.4194]);
    setStops([
      { stop_id: 'stop-1', location: [37.7833, -122.4167], demand: 15 },
      { stop_id: 'stop-2', location: [37.765, -122.42], demand: 25 },
      { stop_id: 'stop-3', location: [37.75, -122.41], demand: 20 },
      { stop_id: 'stop-4', location: [37.79, -122.4], demand: 30 },
      { stop_id: 'stop-5', location: [37.77, -122.45], demand: 18 },
    ]);
  };

  const handleRemoveStop = (id: string) => {
    setStops(stops.filter((s) => s.stop_id !== id));
  };

  const handleSubmit = () => {
    const req: OptimizeRequest = {
      company_id: companyId,
      depot_location: depot,
      stops: stops,
      solver_type: solverType,
      distance_provider: distanceProvider,
    };
    onOptimize(req);
  };

  return (
    <aside className="panel sidebar-left flex flex-col gap-4 overflow-y-auto">
      <div className="flex justify-between items-center pb-2 border-b border-white/10">
        <h2 className="text-lg font-bold text-white flex items-center gap-2">
          <Zap className="w-5 h-5 text-cyan-400" />
          Route Studio Config
        </h2>
        <button
          type="button"
          onClick={handleLoadSampleData}
          className="btn-secondary text-xs py-1 px-2.5 flex items-center gap-1"
        >
          <Sparkles className="w-3.5 h-3.5 text-amber-400" />
          Load SF Sample
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-semibold text-slate-300 mb-1 block">Solver Engine</label>
          <select
            className="input-field text-sm"
            value={solverType}
            onChange={(e) => setSolverType(e.target.value as 'ortools' | 'heuristic')}
          >
            <option value="ortools">Google OR-Tools VRP</option>
            <option value="heuristic">Greedy Nearest Neighbor</option>
          </select>
        </div>

        <div>
          <label className="text-xs font-semibold text-slate-300 mb-1 block">Distance Matrix</label>
          <select
            className="input-field text-sm"
            value={distanceProvider}
            onChange={(e) => setDistanceProvider(e.target.value as 'osrm' | 'haversine')}
          >
            <option value="osrm">OSRM Road Router</option>
            <option value="haversine">Haversine Fallback</option>
          </select>
        </div>
      </div>

      <div>
        <label className="text-xs font-semibold text-slate-300 mb-1 block flex items-center gap-1">
          <MapPin className="w-3.5 h-3.5 text-emerald-400" />
          Central Depot Coordinates [Lat, Lng]
        </label>
        <div className="grid grid-cols-2 gap-2">
          <input
            type="number"
            step="0.0001"
            className="input-field text-xs"
            value={depot[0]}
            onChange={(e) => setDepot([parseFloat(e.target.value) || 0, depot[1]])}
            placeholder="Lat"
          />
          <input
            type="number"
            step="0.0001"
            className="input-field text-xs"
            value={depot[1]}
            onChange={(e) => setDepot([depot[0], parseFloat(e.target.value) || 0])}
            placeholder="Lng"
          />
        </div>
      </div>

      <form onSubmit={handleAddStop} className="p-3 rounded-lg bg-white/5 border border-white/10 flex flex-col gap-2">
        <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider">Add Delivery Stop</h3>
        <div className="grid grid-cols-3 gap-2">
          <input
            type="number"
            step="0.0001"
            placeholder="Lat"
            className="input-field text-xs"
            value={newStopLat}
            onChange={(e) => setNewStopLat(e.target.value)}
          />
          <input
            type="number"
            step="0.0001"
            placeholder="Lng"
            className="input-field text-xs"
            value={newStopLng}
            onChange={(e) => setNewStopLng(e.target.value)}
          />
          <input
            type="number"
            placeholder="Demand"
            className="input-field text-xs"
            value={newStopDemand}
            onChange={(e) => setNewStopDemand(e.target.value)}
          />
        </div>
        <button type="submit" className="btn-secondary text-xs py-1.5 mt-1">
          + Add Stop
        </button>
      </form>

      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex justify-between items-center mb-1">
          <span className="text-xs font-semibold text-slate-300">
            Active Delivery Locations ({stops.length})
          </span>
          {stops.length > 0 && (
            <button
              type="button"
              onClick={() => setStops([])}
              className="text-xs text-rose-400 hover:underline"
            >
              Clear All
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto space-y-1.5 pr-1 max-h-48">
          {stops.length === 0 ? (
            <div className="text-xs text-slate-500 text-center py-6 border border-dashed border-white/10 rounded-lg">
              No stops added yet. Load sample data or add manually.
            </div>
          ) : (
            stops.map((st) => (
              <div
                key={st.stop_id}
                className="flex items-center justify-between p-2 rounded bg-white/5 border border-white/5 text-xs hover:border-cyan-500/30 transition-all"
              >
                <div>
                  <span className="font-semibold text-cyan-300 block">{st.stop_id}</span>
                  <span className="text-slate-400">
                    [{st.location[0].toFixed(4)}, {st.location[1].toFixed(4)}] ? Demand: {st.demand}
                  </span>
                </div>
                <button
                  onClick={() => handleRemoveStop(st.stop_id)}
                  className="text-slate-500 hover:text-rose-400 text-sm px-1.5"
                >
                  ?
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      <button
        onClick={handleSubmit}
        disabled={isLoading || stops.length === 0}
        className="btn-primary w-full py-3 text-sm font-semibold flex items-center justify-center gap-2 mt-auto shadow-lg shadow-cyan-500/20"
      >
        {isLoading ? (
          <>
            <RefreshCw className="w-4 h-4 animate-spin text-cyan-400" />
            Optimizing Routes...
          </>
        ) : (
          <>
            <Play className="w-4 h-4 fill-cyan-400 text-cyan-400" />
            Solve & Optimize Fleet
          </>
        )}
      </button>
    </aside>
  );
};
