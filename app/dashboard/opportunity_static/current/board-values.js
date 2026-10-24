// Presentation numbers and exact settings equality; no transport state.
export const numeric = (v) => {
  if (v == null) return null;
  const [a, b] = String(v).split("/");
  const n = Number(a) / (b === undefined ? 1 : Number(b));
  return Number.isFinite(n) ? n : null;
};
export const money = (v) =>
  numeric(v) === null
    ? "Unknown"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(numeric(v));
export const percent = (v) =>
  numeric(v) === null ? "Unknown" : numeric(v).toFixed(2) + "%";
export const quantity = (v) =>
  numeric(v) === null
    ? "Unknown"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(
        numeric(v),
      );
const ratio = (value) => {
  const parts = String(value).split("/");
  if (parts.length > 2) throw Error("Invalid exact amount");
  const decimal = (text) => {
    const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(text);
    if (!match || text.length > 256) throw Error("Invalid exact amount");
    return [
      BigInt((match[1] === "-" ? "-" : "") + match[2] + (match[3] || "")),
      10n ** BigInt((match[3] || "").length),
    ];
  };
  const a = decimal(parts[0]),
    b = parts.length === 2 ? decimal(parts[1]) : [1n, 1n];
  if (!b[0]) throw Error("Invalid exact amount");
  return [a[0] * b[1], a[1] * b[0]];
};
export const decimalEqual = (a, b) => {
  try {
    const x = ratio(a),
      y = ratio(b);
    return x[0] * y[1] === y[0] * x[1];
  } catch {
    return false;
  }
};
