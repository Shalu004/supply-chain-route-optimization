import { useState, useEffect } from 'react';
import { Navbar } from './components/Navbar';
import { OptimizationForm } from './components/OptimizationForm';
import { MapView } from './components/MapView';
import { MetricsDashboard } from './components/MetricsDashboard';
import { FleetManager } from './components/FleetManager';
import { RunHistory } from './components/RunHistory';
import { AuthModal } from './components/AuthModal';

import type {
  StopInput,
  OptimizeRequest,
  OptimizeResponse,
  Vehicle,
  RunHistoryItem,
  UserSession,
} from './types';

import {
  runOptimization,
  fetchFleet,
  createVehicle,
  deleteVehicle,
  fetchRunHistory,
} from './api';

export function App() {
  const [activeTab, setActiveTab] = useState<'studio' | 'fleet' | 'history'>('studio');
  const [session, setSession] = useState<UserSession | null>(null);
  const [isAuthOpen, setIsAuthOpen] = useState(false);

  const [depot, setDepot] = useState<[number, number]>([37.7749, -122.4194]);
  const [stops, setStops] = useState<StopInput[]>([
    { stop_id: 'stop-1', location: [37.7833, -122.4167], demand: 15 },
    { stop_id: 'stop-2', location: [37.765, -122.42], demand: 25 },
    { stop_id: 'stop-3', location: [37.75, -122.41], demand: 20 },
    { stop_id: 'stop-4', location: [37.79, -122.4], demand: 30 },
  ]);
  const [solverType, setSolverType] = useState<'ortools' | 'heuristic'>('ortools');
  const [distanceProvider, setDistanceProvider] = useState<'osrm' | 'haversine'>('osrm');
  const [optimizationResponse, setOptimizationResponse] = useState<OptimizeResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [history, setHistory] = useState<RunHistoryItem[]>([]);

  const companyId = session ? session.companyId : '00000000-0000-0000-0000-000000000001';

  useEffect(() => {
    async function loadData() {
      if (companyId) {
        const vList = await fetchFleet(companyId, session?.token);
        setVehicles(vList);
        const hList = await fetchRunHistory(companyId, session?.token);
        setHistory(hList);
      }
    }
    loadData();
  }, [companyId, session, activeTab]);

  const handleOptimize = async (req: OptimizeRequest) => {
    setIsLoading(true);
    try {
      const res = await runOptimization(req, session?.token);
      setOptimizationResponse(res);
      const hList = await fetchRunHistory(companyId, session?.token);
      setHistory(hList);
    } catch (err: any) {
      alert('Optimization failed: ' + err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateVehicle = async (
    vData: Omit<Vehicle, 'id' | 'company_id' | 'created_at'>
  ) => {
    setIsLoading(true);
    try {
      const newV = await createVehicle(companyId, vData, session?.token);
      setVehicles([...vehicles, newV]);
    } catch (err: any) {
      alert('Failed to add vehicle: ' + err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteVehicle = async (id: string) => {
    setIsLoading(true);
    try {
      const ok = await deleteVehicle(id, session?.token);
      if (ok) {
        setVehicles(vehicles.filter((v) => v.id !== id));
      }
    } catch (err: any) {
      alert('Failed to delete vehicle: ' + err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="app-container">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        session={session}
        onOpenAuth={() => setIsAuthOpen(true)}
        onLogout={() => setSession(null)}
      />

      <main className="main-content">
        {activeTab === 'studio' && (
          <>
            <OptimizationForm
              onOptimize={handleOptimize}
              isLoading={isLoading}
              companyId={companyId}
              stops={stops}
              setStops={setStops}
              depot={depot}
              setDepot={setDepot}
              solverType={solverType}
              setSolverType={setSolverType}
              distanceProvider={distanceProvider}
              setDistanceProvider={setDistanceProvider}
            />

            <MapView
              depot={depot}
              stops={stops}
              routes={optimizationResponse?.routes}
            />

            <MetricsDashboard response={optimizationResponse} />
          </>
        )}

        {activeTab === 'fleet' && (
          <FleetManager
            vehicles={vehicles}
            onCreateVehicle={handleCreateVehicle}
            onDeleteVehicle={handleDeleteVehicle}
            isLoading={isLoading}
          />
        )}

        {activeTab === 'history' && (
          <RunHistory
            history={history}
            onSelectRun={(run) => {
              setOptimizationResponse({
                status: run.status,
                routes: run.routes,
                unassigned: run.unassigned_stops || [],
                total_distance_km: run.total_distance_km,
                total_cost: run.total_cost,
                execution_time_seconds: run.execution_time_seconds,
                solver_used: run.solver_type,
                run_id: run.id,
              });
              setActiveTab('studio');
            }}
          />
        )}
      </main>

      <AuthModal
        isOpen={isAuthOpen}
        onClose={() => setIsAuthOpen(false)}
        onSuccess={(sess) => setSession(sess)}
      />
    </div>
  );
}

export default App;
