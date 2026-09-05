import { describe, it, expect, vi, beforeEach } from "vitest";
import { forwardRef } from "react";
import { renderWithProviders, screen } from "../test/test-utils";
import LocationPicker from "./LocationPicker";

const setViewMock = vi.fn();
let capturedClickHandler: ((event: { latlng: { lat: number; lng: number } }) => void) | null = null;

vi.mock("leaflet", () => ({
  default: {
    Icon: {
      Default: {
        prototype: {},
        mergeOptions: vi.fn(),
      },
    },
  },
}));

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => <div data-testid="map-container">{children}</div>,
  TileLayer: () => null,
  Marker: forwardRef(function Marker(_props: unknown, _ref: unknown) {
    return null;
  }),
  useMap: () => ({ setView: setViewMock }),
  useMapEvents: (handlers: { click: (event: { latlng: { lat: number; lng: number } }) => void }) => {
    capturedClickHandler = handlers.click;
    return null;
  },
}));

vi.mock("leaflet/dist/images/marker-icon-2x.png", () => ({ default: "icon2x.png" }));
vi.mock("leaflet/dist/images/marker-icon.png", () => ({ default: "icon.png" }));
vi.mock("leaflet/dist/images/marker-shadow.png", () => ({ default: "shadow.png" }));

describe("LocationPicker", () => {
  beforeEach(() => {
    setViewMock.mockClear();
    capturedClickHandler = null;
  });

  it("shows the 'no location selected' hint when value is null", () => {
    renderWithProviders(<LocationPicker value={null} onChange={vi.fn()} />);
    expect(screen.getByText("No location selected yet. Use your location or tap the map to place the pin.")).toBeInTheDocument();
  });

  it("shows the 'location selected' hint when value is set", () => {
    renderWithProviders(<LocationPicker value={{ lat: 12, lon: 34 }} onChange={vi.fn()} />);
    expect(screen.getByText("Location selected. Drag the pin if you need to make it more precise.")).toBeInTheDocument();
  });

  it("calls onChange with clicked lat/lng via the captured map click handler", () => {
    const onChange = vi.fn();
    renderWithProviders(<LocationPicker value={null} onChange={onChange} />);

    expect(capturedClickHandler).toBeInstanceOf(Function);
    capturedClickHandler?.({ latlng: { lat: 10.5, lng: 20.5 } });

    expect(onChange).toHaveBeenCalledWith({ lat: 10.5, lon: 20.5 });
  });

  it("calls map.setView via Recenter's effect when recenter is provided", () => {
    renderWithProviders(<LocationPicker value={null} onChange={vi.fn()} recenter={[1, 2]} />);
    expect(setViewMock).toHaveBeenCalledWith([1, 2], 16);
  });

  it("does not call setView when recenter is not provided", () => {
    renderWithProviders(<LocationPicker value={null} onChange={vi.fn()} />);
    expect(setViewMock).not.toHaveBeenCalled();
  });
});
