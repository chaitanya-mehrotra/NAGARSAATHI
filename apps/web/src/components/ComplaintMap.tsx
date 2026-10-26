import React, { useEffect, useState } from "react";
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  useMap,
  useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { LocateFixed, Maximize2 } from "lucide-react";

export interface MapRow {
  id: string | number;
  latitude: number;
  longitude: number;
  issue_type?: string;
  claimed_category?: string;
  description?: string;
  status?: string;
  public_reference?: string;
}

const DEFAULT_CENTER: [number, number] = [12.93, 77.63]; // Southeast Bengaluru pilot center

const categoryLabels: Record<string, string> = {
  pothole: "Pothole",
  garbage_accumulation: "Garbage",
  sewage_overflow: "Sewage",
  streetlight_failure: "Streetlight",
  other_civic_issue: "Other Issue",
};

const statusLabels: Record<string, string> = {
  submitted: "Submitted",
  processing: "Processing",
  awaiting_review: "Under Review",
  open: "Open",
  admitted: "Admitted",
  assigned: "Assigned",
  in_progress: "In Progress",
  resolution_pending: "Verification Pending",
  resolved: "Resolved",
  rejected: "Rejected",
  out_of_scope: "Out of Scope",
};

function createPinIcon(type: string = "pothole") {
  return L.divIcon({
    className: "custom-leaflet-marker",
    html: `<span class="map-pin ${type}"><span></span></span>`,
    iconSize: [30, 36],
    iconAnchor: [15, 36],
    popupAnchor: [0, -32],
  });
}

function MapController({
  rows,
  selected,
  fitTrigger,
  point,
  onPoint,
  locate,
}: {
  rows: MapRow[];
  selected?: MapRow | null;
  fitTrigger: number;
  point?: [number, number] | null;
  onPoint?: (coord: [number, number]) => void;
  locate?: [number, number] | null;
}) {
  const map = useMap();

  useMapEvents({
    click: (e) => onPoint?.([e.latlng.lat, e.latlng.lng]),
  });

  useEffect(() => {
    map.invalidateSize();
  }, [map]);

  useEffect(() => {
    if (selected && selected.latitude && selected.longitude) {
      map.flyTo(
        [selected.latitude, selected.longitude],
        Math.max(map.getZoom(), 15),
        { animate: !window.matchMedia("(prefers-reduced-motion: reduce)").matches }
      );
    }
  }, [selected, map]);

  useEffect(() => {
    if (fitTrigger && rows.length > 0) {
      const validPoints = rows
        .filter((r) => r.latitude && r.longitude)
        .map((r) => [r.latitude, r.longitude] as [number, number]);
      if (validPoints.length > 0) {
        map.fitBounds(validPoints, { padding: [40, 40], maxZoom: 16 });
      }
    }
  }, [fitTrigger, rows, map]);

  useEffect(() => {
    if (locate) {
      map.setView(locate, 15);
    }
  }, [locate, map]);

  useEffect(() => {
    if (point) {
      map.panTo(point);
    }
  }, [point, map]);

  return null;
}

export interface ComplaintMapProps {
  rows?: MapRow[];
  selected?: MapRow | null;
  onSelect?: (row: MapRow) => void;
  onDetails?: (row: MapRow) => void;
  point?: [number, number] | null;
  onPoint?: (coord: [number, number]) => void;
}

export default function ComplaintMap({
  rows = [],
  selected,
  onSelect,
  onDetails,
  point,
  onPoint,
}: ComplaintMapProps) {
  const [fitTrigger, setFitTrigger] = useState(0);
  const [locate, setLocate] = useState<[number, number] | null>(null);
  const [error, setError] = useState("");

  const tileUrl =
    (import.meta as any).env?.VITE_TILE_URL ||
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  const tileAttribution =
    (import.meta as any).env?.VITE_TILE_ATTRIBUTION ||
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

  function handleGps() {
    if (!navigator.geolocation) {
      setError("Geolocation is not supported by your browser. Please click the map to place a pin.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const coords: [number, number] = [pos.coords.latitude, pos.coords.longitude];
        setLocate(coords);
        onPoint?.(coords);
        setError("");
      },
      () => {
        setError("Could not access your location. Please drop a pin manually on the map.");
      },
      { timeout: 10000, enableHighAccuracy: true }
    );
  }

  return (
    <div className="map-wrap" style={{ position: "relative", width: "100%", height: "100%", minHeight: "400px" }}>
      <MapContainer
        center={point || (rows[0] ? [rows[0].latitude, rows[0].longitude] : DEFAULT_CENTER)}
        zoom={13}
        scrollWheelZoom
        className="leaflet-map"
        style={{ width: "100%", height: "100%", minHeight: "400px", borderRadius: "12px" }}
      >
        <TileLayer url={tileUrl} attribution={tileAttribution} />
        <MapController
          rows={rows}
          selected={selected}
          fitTrigger={fitTrigger}
          point={point}
          onPoint={onPoint}
          locate={locate}
        />

        {/* Selected location marker during complaint intake */}
        {point && (
          <Marker position={point} icon={createPinIcon("selected")}>
            <Popup>
              <strong>Selected Location</strong>
              <br />
              {point[0].toFixed(5)}, {point[1].toFixed(5)}
            </Popup>
          </Marker>
        )}

        {/* Issue / Complaint markers */}
        {rows.map((row) => {
          if (!row.latitude || !row.longitude) return null;
          const cat = row.issue_type || row.claimed_category || "pothole";
          const st = row.status || "open";

          return (
            <Marker
              key={row.id}
              position={[row.latitude, row.longitude]}
              icon={createPinIcon(cat)}
              eventHandlers={{
                click: () => onSelect?.(row),
              }}
            >
              <Popup>
                <div style={{ padding: "4px" }}>
                  <div style={{ fontWeight: 700, fontSize: "14px", marginBottom: "4px" }}>
                    {categoryLabels[cat] || cat}
                  </div>
                  <div style={{ fontSize: "12px", color: "#666", marginBottom: "8px" }}>
                    Status: <strong>{statusLabels[st] || st}</strong>
                  </div>
                  {row.description && (
                    <p style={{ fontSize: "12px", margin: "0 0 8px 0", maxWidth: "200px" }}>
                      {row.description.length > 80
                        ? `${row.description.slice(0, 80)}...`
                        : row.description}
                    </p>
                  )}
                  {onDetails && (
                    <button
                      className="primary"
                      style={{ fontSize: "11px", padding: "4px 8px" }}
                      onClick={(e) => {
                        e.stopPropagation();
                        onDetails(row);
                      }}
                    >
                      View Details
                    </button>
                  )}
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>

      {/* Map Action Controls Overlay */}
      <div
        className="map-actions"
        style={{
          position: "absolute",
          top: "12px",
          right: "12px",
          zIndex: 1000,
          display: "flex",
          gap: "8px",
        }}
      >
        <button
          type="button"
          className="map-btn"
          title="Fit all markers"
          onClick={() => setFitTrigger((prev) => prev + 1)}
          style={{
            background: "#fff",
            border: "1px solid #ccc",
            borderRadius: "6px",
            padding: "8px",
            display: "flex",
            alignItems: "center",
            boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
          }}
        >
          <Maximize2 size={16} />
        </button>
        <button
          type="button"
          className="map-btn"
          title="Detect my location"
          onClick={handleGps}
          style={{
            background: "#fff",
            border: "1px solid #ccc",
            borderRadius: "6px",
            padding: "8px",
            display: "flex",
            alignItems: "center",
            boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
          }}
        >
          <LocateFixed size={16} />
        </button>
      </div>

      {error && (
        <div
          role="alert"
          style={{
            position: "absolute",
            bottom: "12px",
            left: "12px",
            right: "12px",
            zIndex: 1000,
            background: "#fee2e2",
            color: "#b91c1c",
            padding: "8px 12px",
            borderRadius: "6px",
            fontSize: "12px",
            border: "1px solid #f87171",
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}
