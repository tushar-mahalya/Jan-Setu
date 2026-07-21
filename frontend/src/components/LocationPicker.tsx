import { useCallback, useEffect, useMemo, useRef } from "react";
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";
import { useI18n } from "../i18n/I18nContext";

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
  /** Set by the parent (e.g. "Use my location") to pan/zoom the map to a point. */
  recenter?: [number, number] | null;
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

export default function LocationPicker({ value, onChange, recenter }: LocationPickerProps) {
  const { t } = useI18n();
  const position: [number, number] = value ? [value.lat, value.lon] : FALLBACK_CENTER;
  const handleMove = useCallback((lat: number, lon: number) => onChange({ lat, lon }), [onChange]);

  return (
    <div className="location-picker">
      <div className="location-picker__map" role="application" aria-label={t.mapAria}>
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
      <p className="field__hint">
        {value ? t.hintSelected : t.hintNone}
      </p>
    </div>
  );
}
