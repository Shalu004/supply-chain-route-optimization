export interface StopInput {
  stop_id: string;
  location: [number, number];
  demand: number;
  time_window?: [number, number];
  service_duration?: number;
  pickup_stop_id?: string;
}

export interface VehicleSpecInput {
  id?: string;
  name: string;
  capacity: number;
  fixed_cost: number;
  cost_per_km: number;
  max_route_distance_km?: number | null;
}

export interface OptimizeRequest {
  company_id: string;
  stops: StopInput[];
  depot_location?: [number, number];
  solver_type?: 'ortools' | 'heuristic';
  distance_provider?: 'osrm' | 'haversine';
  vehicles?: VehicleSpecInput[];
  fleet_vehicle_ids?: string[];
  job_id?: string;
  use_cache?: boolean;
}

export interface RouteStep {
  stop_id: string;
  location: [number, number];
  demand: number;
}

export interface RouteOutput {
  vehicle_id: string;
  vehicle_name?: string;
  route: RouteStep[];
  distance_km: number;
  cost: number;
}

export interface UnassignedStop {
  stop_id: string;
  demand: number;
  reason?: string;
}

export interface OptimizeResponse {
  status: string;
  routes: RouteOutput[];
  unassigned: UnassignedStop[];
  total_distance_km: number;
  total_cost: number;
  execution_time_seconds: number;
  solver_used: string;
  run_id?: string;
}

export interface Vehicle {
  id: string;
  company_id: string;
  name: string;
  capacity: number;
  fixed_cost: number;
  cost_per_km: number;
  max_route_distance_km?: number | null;
  status: string;
  created_at: string;
}

export interface RunHistoryItem {
  id: string;
  created_at: string;
  solver_type: string;
  distance_provider: string;
  total_distance_km: number;
  total_cost: number;
  execution_time_seconds: number;
  status: string;
  routes: RouteOutput[];
  unassigned_stops: UnassignedStop[];
}

export interface UserSession {
  companyId: string;
  companyName: string;
  slug: string;
  token: string;
}
export interface OptimizationProgress {
  job_id: string;
  status: string;
  progress_pct: number;
  message: string;
}
