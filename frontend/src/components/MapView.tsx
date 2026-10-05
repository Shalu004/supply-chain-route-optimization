import React from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { StopInput, RouteOutput } from '../types';

delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

const ROUTE_COLORS = [
  '#06b6d4',
  '#10b981',
  '#8b5cf6',
  '#f59e0b',
  '#ec4899',
  '#3b82f6',
];

interface MapViewProps {
  depot: [number, number];
  stops: StopInput[];
  routes?: RouteOutput[];
}

export const MapView: React.FC<MapViewProps> = ({ depot, stops, routes }) => {
  return (
    <div className="map-container flex-1 h-full relative rounded-xl overflow-hidden shadow-2xl border border-white/10">
      <MapContainer
        center={depot}
        zoom={12}
        style={{ width: '100%', height: '100%', background: '#0b1329' }}
      >
        <TileLayer
          attribution='&copy; OpenStreetMap'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />

        <Marker position={depot}>
          <Popup>
            <div className="text-xs font-semibold text-slate-800">
              Central Logistics Depot<br />
              [{depot[0].toFixed(4)}, {depot[1].toFixed(4)}]
            </div>
          </Popup>
        </Marker>

        {stops.map((st) => (
          <Marker key={st.stop_id} position={st.location}>
            <Popup>
              <div className="text-xs text-slate-800">
                <strong>Stop: {st.stop_id}</strong><br />
                Demand: {st.demand} units
              </div>
            </Popup>
          </Marker>
        ))}

        {routes && routes.map((rt, idx) => {
          const color = ROUTE_COLORS[idx % ROUTE_COLORS.length];
          const pathCoords: [number, number][] = [
            depot,
            ...rt.route.map((s) => s.location),
            depot,
          ];
          return (
            <Polyline
              key={rt.vehicle_id || idx}
              positions={pathCoords}
              pathOptions={{ color, weight: 4, opacity: 0.8, dashArray: '6, 6' }}
            />
          );
        })}
      </MapContainer>
    </div>
  );
};
