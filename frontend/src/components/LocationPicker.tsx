import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

delete (L.Icon.Default.prototype as unknown as { _getIconUrl?: unknown })._getIconUrl;
L.Icon.Default.mergeOptions({ iconRetinaUrl: markerIcon2x, iconUrl: markerIcon, shadowUrl: markerShadow });

const FALLBACK_CENTER: [number, number] = [28.6139, 77.209];

export interface LocationValue {
  lat: number;
  lon: number;
}

interface LocationPickerProps {
  value: LocationValue | null;
  onChange: (value: LocationValue) => void;
}

function Recenter({ center }: { center: [number, number] }) {
  const map = useMap();
  useEffect(() => {
    map.setView(center, 16);
  }, [center, map]);
  return null;
}

function Pin({
  position,
  onMove,
}: {
  position: [number, number];
  onMove: (lat: number, lon: number) => void;
}) {
  const markerRef = useRef<L.Marker>(null);
  useMapEvents({ click: (event) => onMove(event.latlng.lat, event.latlng.lng) });
  const eventHandlers = useMemo(
    () => ({
      dragend() {
        const point = markerRef.current?.getLatLng();
        if (point) onMove(point.lat, point.lng);
      },
    }),
    [onMove],
  );
  return <Marker draggable position={position} eventHandlers={eventHandlers} ref={markerRef} />;
}

export default function LocationPicker({ value, onChange }: LocationPickerProps) {
  const [position, setPosition] = useState<[number, number]>(
    value ? [value.lat, value.lon] : FALLBACK_CENTER,
  );
  const [recenter, setRecenter] = useState<[number, number] | null>(null);
  const [geoState, setGeoState] = useState<"idle" | "locating" | "found" | "failed">("idle");
  const [geoError, setGeoError] = useState<string | null>(null);
  const [coordinateError, setCoordinateError] = useState<string | null>(null);
  const onChangeRef = useRef(onChange);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const handleMove = useCallback(
    (lat: number, lon: number) => {
      setPosition([lat, lon]);
      setGeoState("found");
      setGeoError(null);
      setCoordinateError(null);
      onChange({ lat, lon });
    },
    [onChange],
  );

  const locateMe = useCallback(() => {
    setGeoError(null);
    if (!navigator.geolocation) {
      setGeoState("failed");
      setGeoError("Location is not supported here. Tap the map to place the pin. / मानचित्र पर पिन लगाएँ।");
      return;
    }

    setGeoState("locating");
    navigator.geolocation.getCurrentPosition(
      (result) => {
        const next: [number, number] = [result.coords.latitude, result.coords.longitude];
        setPosition(next);
        setRecenter(next);
        setGeoState("found");
        onChangeRef.current({ lat: next[0], lon: next[1] });
      },
      (error) => {
        setGeoState("failed");
        const reason =
          error.code === error.PERMISSION_DENIED
            ? "Location permission is off."
            : "We could not find your location.";
        setGeoError(`${reason} Tap the map to place the pin, or try again. / मानचित्र पर पिन लगाएँ या फिर कोशिश करें।`);
      },
      { enableHighAccuracy: true, timeout: 8000 },
    );
  }, []);

  return (
    <div className="location-picker">
      <div className="location-picker__toolbar">
        <button
          type="button"
          className="btn btn--secondary btn-sm"
          onClick={locateMe}
          disabled={geoState === "locating"}
        >
          {geoState === "locating"
            ? "Finding location… / स्थान खोज रहे हैं…"
            : "Use my location / मेरा स्थान"}
        </button>
        {value && (
          <span className="location-picker__selected" role="status">
            Pin selected / पिन चुना गया
          </span>
        )}
      </div>

      {geoError && (
        <div className="notice" data-tone="warning" role="alert">
          <p>{geoError}</p>
        </div>
      )}

      <div className="location-picker__map" role="application" aria-label="Interactive map for choosing complaint location. Use the coordinate fields below to enter a location by keyboard.">
        <MapContainer
          center={position}
          zoom={15}
          scrollWheelZoom={false}
          style={{ height: "100%", width: "100%" }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url={import.meta.env.VITE_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"}
          />
          {recenter && <Recenter center={recenter} />}
          <Pin position={position} onMove={handleMove} />
        </MapContainer>
      </div>
      <fieldset className="coord-readout" aria-describedby={coordinateError ? "location-coordinate-error" : undefined}>
        <legend>{value ? "Selected coordinates" : "Map centre"}</legend>
        <div className="location-picker__coordinate-fields">
          <label htmlFor="location-latitude">Latitude</label>
          <input id="location-latitude" inputMode="decimal" type="number" step="any" min="-90" max="90" value={position[0]} onChange={(event) => {
            const lat = Number(event.target.value);
            if (Number.isFinite(lat) && lat >= -90 && lat <= 90) handleMove(lat, position[1]);
            else setCoordinateError("Enter a latitude between -90 and 90.");
          }} />
          <label htmlFor="location-longitude">Longitude</label>
          <input id="location-longitude" inputMode="decimal" type="number" step="any" min="-180" max="180" value={position[1]} onChange={(event) => {
            const lon = Number(event.target.value);
            if (Number.isFinite(lon) && lon >= -180 && lon <= 180) handleMove(position[0], lon);
            else setCoordinateError("Enter a longitude between -180 and 180.");
          }} />
        </div>
        {coordinateError && <p id="location-coordinate-error" className="field-error" role="alert">{coordinateError}</p>}
      </fieldset>
      <p className="field__hint">
        {value ? "Location selected. Drag the pin if you need to make it more precise." : "No location selected yet. Use your location or tap the map to place the pin."}
      </p>
    </div>
  );
}
