const CATEGORIES: Record<string, string> = {
  produce: "Produce",
  dairy: "Dairy",
  bakery: "Bakery",
  shelf_stable: "Shelf-stable food",
  frozen: "Frozen food",
};

const UNITS: Record<string, string> = {
  crate: "crates",
  case: "cases",
  pound: "pounds",
};

export function categoryLabel(value: string): string {
  return CATEGORIES[value] ?? value;
}

export function storageLabel(value: string): string {
  if (value === "ambient") return "Ambient";
  if (value === "refrigerated") return "Refrigerated";
  if (value === "frozen") return "Frozen";
  return value;
}

export function unitLabel(quantity: number, unit: string): string {
  if (quantity === 1) {
    if (unit === "case") return "1 case";
    if (unit === "crate") return "1 crate";
    if (unit === "pound") return "1 pound";
  }
  return `${quantity} ${UNITS[unit] ?? unit}`;
}

export function when(value: string | null): string {
  if (!value) return "Not reported";
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function statusLabel(value: string): string {
  if (value === "reserved") return "Reserved";
  if (value === "delivered") return "Delivered";
  if (value === "canceled") return "Canceled";
  if (value === "draft") return "Draft";
  return value;
}
