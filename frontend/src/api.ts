import type { OptimizeRequest, OptimizeResponse, Vehicle, RunHistoryItem } from './types';

const API_BASE = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000';

function getHeaders(token?: string): HeadersInit {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = 'Bearer ' + token;
  }
  return headers;
}

export async function registerCompany(name: string, slug: string, password: string): Promise<{ id: string; name: string; slug: string; token: string }> {
  const res = await fetch(API_BASE + '/api/v1/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, slug, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Registration failed' }));
    throw new Error(err.detail || 'Registration failed');
  }
  return res.json();
}

export async function loginCompany(slug: string, password: string): Promise<{ id: string; name: string; slug: string; token: string }> {
  const res = await fetch(API_BASE + '/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Login failed' }));
    throw new Error(err.detail || 'Login failed');
  }
  return res.json();
}

export async function runOptimization(req: OptimizeRequest, token?: string): Promise<OptimizeResponse> {
  const res = await fetch(API_BASE + '/api/v1/optimize', {
    method: 'POST',
    headers: getHeaders(token),
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Optimization request failed' }));
    throw new Error(err.detail || 'Optimization failed');
  }
  return res.json();
}

export async function fetchFleet(companyId: string, token?: string): Promise<Vehicle[]> {
  const res = await fetch(API_BASE + '/api/v1/vehicles?company_id=' + companyId, {
    headers: getHeaders(token),
  });
  if (!res.ok) return [];
  return res.json();
}

export async function createVehicle(companyId: string, vehicleData: Omit<Vehicle, 'id' | 'company_id' | 'created_at'>, token?: string): Promise<Vehicle> {
  const res = await fetch(API_BASE + '/api/v1/vehicles', {
    method: 'POST',
    headers: getHeaders(token),
    body: JSON.stringify({ ...vehicleData, company_id: companyId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to create vehicle' }));
    throw new Error(err.detail || 'Failed to create vehicle');
  }
  return res.json();
}

export async function deleteVehicle(vehicleId: string, token?: string): Promise<boolean> {
  const res = await fetch(API_BASE + '/api/v1/vehicles/' + vehicleId, {
    method: 'DELETE',
    headers: getHeaders(token),
  });
  return res.ok;
}

export async function fetchRunHistory(companyId: string, token?: string): Promise<RunHistoryItem[]> {
  const res = await fetch(API_BASE + '/api/v1/runs?company_id=' + companyId, {
    headers: getHeaders(token),
  });
  if (!res.ok) return [];
  return res.json();
}
