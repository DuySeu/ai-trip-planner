import { MapPin } from "lucide-react";
import { useCurrentLocation, weatherKey } from "../api/location.ts";
import { useT } from "../i18n/LanguageProvider.tsx";

interface Props {
  // Placement in the parent (margin, alignment); the chip's own look stays fixed
  className?: string;
}

// The visitor's city and its weather now, as a weather chip; nothing while it loads, when the IP lookup fails, or
// when the backend could not name the city
export function LocationBanner({ className = "" }: Props) {
  const t = useT();
  const location = useCurrentLocation();

  if (!location.data) return null;
  const { city, weather } = location.data;
  const parts = weather ? [city, `${Math.round(weather.temperature_c)} °C`, t(weatherKey(weather.weather_code))] : [city];

  return (
    <p
      role="status"
      aria-label={t("location.label")}
      className={`inline-flex min-h-7 max-w-full min-w-0 items-center gap-1 rounded-full bg-muted px-3 text-sm text-foreground tabular-nums ${className}`}
    >
      <MapPin size={16} strokeWidth={1.75} aria-hidden="true" className="shrink-0" />
      <span className="truncate">{parts.join(" · ")}</span>
    </p>
  );
}

// The chip at the right of a page header (HomePage, ChatPage) from the desktop breakpoint; below it
// the mobile top bar shows the chip instead
export function HeaderLocation({ className = "" }: Props) {
  return (
    <div className={`hidden min-w-0 lg:flex ${className}`}>
      <LocationBanner />
    </div>
  );
}
