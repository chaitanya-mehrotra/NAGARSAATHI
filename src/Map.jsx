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
import { issueLabels, statusLabels } from "./validation";
const center = [12.9716, 77.5946];
function icon(type) {
  return L.divIcon({
    className: "",
    html: '<span class="map-pin ' + type + '"><span></span></span>',
    iconSize: [30, 36],
    iconAnchor: [15, 36],
  });
}
function Controller({ rows, selected, fit, point, onPoint, locate }) {
  const map = useMap();
  useMapEvents({ click: (e) => onPoint?.([e.latlng.lat, e.latlng.lng]) });
  useEffect(() => {
    map.invalidateSize();
  }, [map]);
  useEffect(() => {
    if (selected)
      map.flyTo(
        [selected.latitude, selected.longitude],
        Math.max(map.getZoom(), 15),
        { animate: !matchMedia("(prefers-reduced-motion: reduce)").matches },
      );
  }, [selected?.id]);
  useEffect(() => {
    if (fit && rows.length)
      map.fitBounds(
        rows.map((r) => [r.latitude, r.longitude]),
        { padding: [40, 40], maxZoom: 16 },
      );
  }, [fit]);
  useEffect(() => {
    if (locate) map.setView(locate, 15);
  }, [locate]);
  useEffect(() => {
    if (point) map.panTo(point);
  }, [point]);
  return null;
}
export default function ComplaintMap({
  rows = [],
  selected,
  onSelect,
  onDetails,
  point,
  onPoint,
}) {
  const [fit, setFit] = useState(0),
    [locate, setLocate] = useState(null),
    [error, setError] = useState("");
  function gps() {
    if (!navigator.geolocation)
      return setError(
        "Location unavailable. You can still explore or place a pin.",
      );
    navigator.geolocation.getCurrentPosition(
      (p) => {
        const v = [p.coords.latitude, p.coords.longitude];
        setLocate(v);
        onPoint?.(v);
        setError("");
      },
      () =>
        setError(
          "Could not access your location. Please place a pin manually.",
        ),
      { timeout: 10000 },
    );
  }
  return (
    <div className="map-wrap">
      <MapContainer
        center={center}
        zoom={12}
        scrollWheelZoom
        className="leaflet-map"
      >
        <TileLayer
          url={
            import.meta.env.VITE_TILE_URL ||
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          }
          attribution={
            import.meta.env.VITE_TILE_ATTRIBUTION ||
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          }
          eventHandlers={{
            tileerror: () =>
              setError(
                "Some map tiles could not load. The complaint list remains available.",
              ),
          }}
        />
        <Controller {...{ rows, selected, fit, point, onPoint, locate }} />
        {rows.map((r) => (
          <Marker
            key={r.id}
            position={[r.latitude, r.longitude]}
            icon={icon(r.issue_type)}
            eventHandlers={{ click: () => onSelect?.(r) }}
          >
            <Popup>
              <strong>{r.reference || `Report #${r.id}`}</strong>
              <p>
                {issueLabels[r.issue_type] || "Issue"} · {statusLabels[r.status] || r.status}
              </p>
              {r.photo_url && (
                <img
                  className="popup-photo"
                  src={
                    r.photo_url.startsWith("http")
                      ? r.photo_url
                      : `http://127.0.0.1:8001${r.photo_url}?token=${localStorage.getItem("nagarsaathi_token") || ""}`
                  }
                  alt="Reported issue"
                />
              )}
              <p>{r.description.slice(0, 90)}</p>
              <small>
                {new Date(
                  typeof r.created_at === "number" && r.created_at < 1e11
                    ? r.created_at * 1000
                    : r.created_at
                ).toLocaleDateString()}
              </small>
              <button className="text-button" onClick={() => onDetails(r)}>
                View details →
              </button>
            </Popup>
          </Marker>
        ))}
        {point && (
          <Marker
            position={point}
            icon={icon("both")}
            draggable
            eventHandlers={{
              dragend: (e) => {
                const p = e.target.getLatLng();
                onPoint([p.lat, p.lng]);
              },
            }}
          />
        )}
      </MapContainer>
      <div className="map-actions">
        <button
          className="map-action"
          onClick={() => setFit((x) => x + 1)}
          disabled={!rows.length}
          title="Fit to loaded results"
        >
          <Maximize2 size={15} /> Fit to results
        </button>
        <button
          className={onPoint ? "map-action" : "map-action square"}
          onClick={gps}
          aria-label={onPoint ? "Use My Location" : "Locate me"}
        >
          <LocateFixed size={17} />
          {onPoint && "Use My Location"}
        </button>
      </div>
      <div className="map-legend">
        <span>
          <i className="dot pothole" /> Pothole
        </span>
        <span>
          <i className="dot waterlogging" /> Waterlogging
        </span>
        <span>
          <i className="dot both" /> Both
        </span>
      </div>
      {error && (
        <div className="map-error" role="status">
          {error}
        </div>
      )}
    </div>
  );
}
