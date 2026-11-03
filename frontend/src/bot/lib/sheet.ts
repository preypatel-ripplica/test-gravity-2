export interface SheetData {
  headers: string[];
  rows: string[][];
}

/** Parse an .xlsx/.xls/.csv file in the browser into header + rows (strings).
 *  SheetJS is loaded on demand so it stays out of the main bundle. */
export async function parseSheetFile(file: File): Promise<SheetData> {
  const XLSX = await import("xlsx");
  const buf = await file.arrayBuffer();
  const wb = XLSX.read(buf, { type: "array" });
  const ws = wb.Sheets[wb.SheetNames[0]];
  const aoa = XLSX.utils.sheet_to_json<unknown[]>(ws, { header: 1, raw: false, defval: "" });
  const nonEmpty = aoa.filter((r) => r.some((c) => String(c ?? "").trim() !== ""));
  if (nonEmpty.length === 0) return { headers: [], rows: [] };
  // Header = the first row that has ≥2 non-empty cells (skips title/subtitle rows).
  const hIdx = Math.max(0, nonEmpty.findIndex((r) => r.filter((c) => String(c ?? "").trim()).length >= 2));
  const headers = nonEmpty[hIdx].map((c) => String(c ?? "").trim());
  const rows = nonEmpty.slice(hIdx + 1).map((r) => headers.map((_, i) => String(r[i] ?? "").trim()));
  return { headers, rows };
}

/** Normalize an Indian mobile: strip non-digits, 10 digits → 91-prefixed. null if invalid. */
export function normalizePhone(raw: string | null | undefined): string | null {
  if (!raw) return null;
  let d = String(raw).replace(/\D/g, "");
  if (d.length === 10) d = "91" + d;
  if (d.length === 12 && d.startsWith("91")) return d;
  return null;
}

/** Guess which columns hold name / phone from header text. */
export function guessColumns(headers: string[]): { name: number; phone: number } {
  const find = (re: RegExp) => headers.findIndex((h) => re.test(h.toLowerCase()));
  const phone = find(/phone|mobile|number|whatsapp|contact/);
  const name = find(/name|patient|customer/);
  return { name: name >= 0 ? name : 0, phone: phone >= 0 ? phone : Math.min(1, headers.length - 1) };
}

export interface ParsedRecipient {
  name: string;
  phone: string;
  extras: string[];
}
export interface ParseResult {
  recipients: ParsedRecipient[];
  duplicates: number;
  invalid: { name: string; raw: string }[];
}

/** Map sheet rows → recipients: normalize phones, drop invalid, dedupe by phone. */
export function toRecipients(data: SheetData, nameCol: number, phoneCol: number, extraCols: number[] = []): ParseResult {
  const seen = new Set<string>();
  const recipients: ParsedRecipient[] = [];
  const invalid: { name: string; raw: string }[] = [];
  let duplicates = 0;
  for (const r of data.rows) {
    const name = (r[nameCol] ?? "").trim();
    const raw = r[phoneCol] ?? "";
    const phone = normalizePhone(raw);
    if (!phone) { invalid.push({ name, raw }); continue; }
    if (seen.has(phone)) { duplicates++; continue; }
    seen.add(phone);
    recipients.push({ name, phone, extras: extraCols.map((c) => (r[c] ?? "").trim()) });
  }
  return { recipients, duplicates, invalid };
}
