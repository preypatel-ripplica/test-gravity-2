import type { Template, TemplateComponent } from "../types";

/** BODY text of a template, "" if none. */
export function templateBody(components: TemplateComponent[]): string {
  return components.find((c) => c.type === "BODY")?.text ?? "";
}

/** FOOTER text of a template, "" if none. */
export function templateFooter(components: TemplateComponent[]): string {
  return components.find((c) => c.type === "FOOTER")?.text ?? "";
}

/** Highest {{n}} in the BODY — mirrors services._count_body_variables. */
export function countBodyVariables(components: TemplateComponent[]): number {
  const body = templateBody(components);
  let max = 0;
  for (const m of body.matchAll(/{{\s*(\d+)\s*}}/g)) max = Math.max(max, parseInt(m[1], 10));
  return max;
}

/**
 * The BODY with {{1}},{{2}}… filled from params in order — mirrors
 * services.render_template_body so a sent template reads exactly as the
 * customer received it. Unfilled placeholders are left as-is.
 */
export function renderTemplateBody(components: TemplateComponent[], params: string[] = []): string {
  return templateBody(components).replace(/{{\s*(\d+)\s*}}/g, (m, n) => {
    const i = parseInt(n, 10) - 1;
    return i >= 0 && i < params.length ? String(params[i]) : m;
  });
}

/** First name for a {{1}} greeting: strip a leading title, take the first token. */
export function firstName(full: string | null | undefined): string {
  const titles = new Set(["mr", "mrs", "ms", "dr", "smt", "shri"]);
  let toks = (full ?? "").trim().split(/\s+/).filter(Boolean);
  while (toks.length > 1 && titles.has(toks[0].toLowerCase().replace(/\.$/, ""))) toks = toks.slice(1);
  return toks[0] ?? "there";
}

/** Build a Template's components from a simple body/footer pair (submit form). */
export function componentsFrom(body: string, footer?: string): TemplateComponent[] {
  const comps: TemplateComponent[] = [{ type: "BODY", text: body }];
  const n = countBodyVariables(comps);
  if (n > 0) comps[0].example = { body_text: [Array.from({ length: n }, (_, i) => `Sample ${i + 1}`)] };
  if (footer && footer.trim()) comps.push({ type: "FOOTER", text: footer.trim() });
  return comps;
}

export const isSendable = (t: Template) => t.status === "APPROVED";
