/**
 * Reverse geocoding for the report form: turns a map pin into a short, human landmark
 * ("Forum Mall, Hosur Road, Koramangala"). Uses OpenStreetMap Nominatim by default;
 * set VITE_GEOCODE_URL to point at your own Nominatim-compatible service in production.
 */
export async function nearbyLandmark(
  latitude: number,
  longitude: number,
  lang: "en" | "kn",
  signal?: AbortSignal,
): Promise<string | null> {
  const base = ((import.meta as any).env?.VITE_GEOCODE_URL || "https://nominatim.openstreetmap.org").replace(/\/$/, "");
  const params = new URLSearchParams({
    format: "jsonv2",
    lat: String(latitude),
    lon: String(longitude),
    zoom: "18",
    addressdetails: "1",
    // Kannada names where OSM has them, English otherwise.
    "accept-language": lang === "kn" ? "kn,en" : "en",
  });
  const response = await fetch(`${base}/reverse?${params}`, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) return null;
  return describePlace(await response.json());
}

export function describePlace(data: any): string | null {
  if (!data || data.error) return null;
  const a = data.address ?? {};
  const place =
    data.name || a.amenity || a.shop || a.tourism || a.building || a.leisure || a.office || a.historic || a.place;
  const road = a.road || a.pedestrian || a.footway || a.residential;
  const area = a.neighbourhood || a.suburb || a.quarter || a.city_district;
  const parts: string[] = [];
  for (const part of [place, road, area]) {
    if (part && !parts.includes(part)) parts.push(String(part).trim());
  }
  const text = parts.length
    ? parts.join(", ")
    : String(data.display_name ?? "").split(",").slice(0, 3).join(",").trim();
  return text ? text.slice(0, 150) : null;
}
