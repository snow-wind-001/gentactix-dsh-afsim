import profiles from "../../gentactix/unit_types.json";

// Exact aliases must not turn e.g. 装甲侦察 into generic armor.
export function classifyUnit(unitType: unknown) {
  const text = String(unitType ?? "").trim().toLowerCase();
  return profiles.find((p) => p.id === text || (p as { aliases?: string[] }).aliases?.includes(text))
    ?? profiles.find((p) => p.keywords.some((k) => text.includes(k)));
}
