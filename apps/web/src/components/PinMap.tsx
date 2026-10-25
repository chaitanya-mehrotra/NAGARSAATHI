import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";

maplibregl.setWorkerUrl(workerUrl);

export function PinMap({
  longitude,
  latitude,
  onPin,
}: {
  longitude: number;
  latitude: number;
  onPin?: (longitude: number, latitude: number) => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const marker = useRef<maplibregl.Marker | null>(null);
  const callback = useRef(onPin);
  callback.current = onPin;
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!root.current) return;
    let active = true;
    try {
      const instance = new maplibregl.Map({
        container: root.current,
        center: [77.645, 12.93],
        zoom: 12,
        style: {
          version: 8,
          sources: {},
          layers: [
            {
              id: "background",
              type: "background",
              paint: { "background-color": "#e5ede5" },
            },
          ],
        },
        attributionControl: false,
      });
      map.current = instance;
      marker.current = new maplibregl.Marker({ color: "#b45309" })
        .setLngLat([longitude, latitude])
        .addTo(instance);
      instance.on("error", () => active && setFailed(true));
      instance.on("click", (event) =>
        callback.current?.(event.lngLat.lng, event.lngLat.lat),
      );
      instance.on("load", () => {
        fetch("/api/v1/config/boundaries")
          .then((response) => {
            if (!response.ok) throw new Error("Boundary unavailable");
            return response.json();
          })
          .then((data) => {
            if (!active) return;
            instance.addSource("areas", { type: "geojson", data });
            instance.addLayer({
              id: "areas",
              type: "line",
              source: "areas",
              paint: { "line-color": "#466d60", "line-width": 2 },
            });
          })
          .catch(() => active && setFailed(true));
      });
    } catch {
      setFailed(true);
    }
    return () => {
      active = false;
      marker.current?.remove();
      map.current?.remove();
      map.current = null;
    };
    // The map is created once; a separate effect updates its marker.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    marker.current?.setLngLat([longitude, latitude]);
  }, [longitude, latitude]);
  return (
    <>
      <div
        className="pin-map"
        ref={root}
        role="img"
        aria-label="Pilot outlines and issue pin"
      />
      <p className="hint">
        {failed
          ? "Map unavailable. Enter coordinates below."
          : "Demo outlines only; no street tiles. Click to place a pin or enter coordinates below."}
      </p>
    </>
  );
}
