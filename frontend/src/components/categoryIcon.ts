import {
  BedDouble,
  Bus,
  Camera,
  Car,
  type LucideIcon,
  Motorbike,
  Plane,
  Ship,
  ShoppingBag,
  Ticket,
  TrainFront,
  Utensils,
} from "lucide-react";
import type { Category, TransportMode } from "../api/api.types.ts";

const MODE_ICON: Record<TransportMode, LucideIcon> = {
  flight: Plane,
  train: TrainFront,
  bus: Bus,
  car: Car,
  motorbike: Motorbike,
  boat: Ship,
};

const CATEGORY_ICON: Record<Exclude<Category, "transport">, LucideIcon> = {
  accommodation: BedDouble,
  food: Utensils,
  shopping: ShoppingBag,
  service: Ticket,
  sightseeing: Camera,
};

// The icon that tells plan items apart (DESIGN.md section 7); transport goes by mode
export function categoryIcon(category: Category, mode: TransportMode | null): LucideIcon {
  if (category === "transport") return mode ? MODE_ICON[mode] : Bus;
  return CATEGORY_ICON[category];
}
