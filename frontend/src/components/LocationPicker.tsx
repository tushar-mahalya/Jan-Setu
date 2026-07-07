import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

// Leaflet's default marker icon references relative paths that break under
// bundlers like Vite — point it at the bundled asset URLs instead.
delete (L.Icon.Default.prototype as unknown as { _getIconUrl?: unknown })._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

const FALLBACK_CENTER: [number, number] = [28.6139, 77.209]; // New Delhi, used until geolocation resolves

export interface LocationValue {
  lat: number;
  lon: number;
}

interface LocationPickerProps {
  value: LocationValue | null;
  onChange: (value: LocationValue) => void;
}

function RecenterOnce({ center }: { center: [number, number] }) {
  const map = useMap();
  const appliedRef = useRef(false);
  useEffect(() => {
    if (appliedRef.current) return;
    appliedRef.current = true;
    map.setView(center, 16);
  }, [center, map]);
  return null;
}

function DraggableMarker({
  position,
  onMove,
}: {
  position: [number, number];
  onMove: (lat: number, lon: number) => void;
}) {
  const markerRef = useRef<L.Marker>(null);

  useMapEvents({
    click(event) {
      onMove(event.latlng.lat, event.latlng.lng);
    },
  });

  const eventHandlers = useMemo(
    () => ({
      dragend() {
        const marker = markerRef.current;
        if (marker) {
          const latLng = marker.getLatLng();
          onMove(latLng.lat, latLng.lng);
        }
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
  const [recenterSignal, setRecenterSignal] = useState<[number, number] | null>(null);

  useEffect(() => {
    if (value || !navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const next: [number, number] = [pos.coords.latitude, pos.coords.longitude];
        setPosition(next);
        setRecenterSignal(next);
        onChange({ lat: next[0], lon: next[1] });
      },
      () => {
        // Permission denied or unavailable — user can still drag the pin manually.
      },
      { enableHighAccuracy: true, timeout: 8000 },
    );
    // Only ever attempt this once, on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleMove = useCallback(
    (lat: number, lon: number) => {
      setPosition([lat, lon]);
      onChange({ lat, lon });
    },
    [onChange],
  );

  return (
    <div>
      <div className="location-picker__map">
        <MapContainer center={position} zoom={15} scrollWheelZoom style={{ height: "100%", width: "100%" }}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {recenterSignal && <RecenterOnce center={recenterSignal} />}
          <DraggableMarker position={position} onMove={handleMove} />
        </MapContainer>
      </div>
      <p className="location-picker__coords mono">
        {position[0].toFixed(5)}, {position[1].toFixed(5)}
      </p>
      <p className="field__hint">Drag the pin or tap the map to adjust the exact location.</p>
    </div>
  );
}
