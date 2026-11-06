/** Power Automate body routing helpers (mirror of API contract). */

export const PA_SUBJECT = "[TEAMS] Maintenance Alert";
export const PA_ROUTING_LINE = "To: {{teams_target_email}}";

export function splitPaRouting(plain: string): { routing: string; content: string } {
  const lines = plain.split(/\r?\n/);
  if (lines[0] && /^To:\s*/i.test(lines[0])) {
    let i = 1;
    while (i < lines.length && !lines[i].trim()) i += 1;
    return { routing: lines[0], content: lines.slice(i).join("\n") };
  }
  return { routing: PA_ROUTING_LINE, content: plain };
}

export function joinPaRouting(content: string): string {
  const body = content.replace(/^\s+/, "");
  return body ? `${PA_ROUTING_LINE}\n\n${body}` : `${PA_ROUTING_LINE}\n\n`;
}

export function isPaStyle(opts: {
  key?: string;
  channel?: string;
  subject?: string;
  bodyPlain?: string;
}): boolean {
  if ((opts.key || "").startsWith("pa.")) return true;
  if (opts.channel === "bridge") return true;
  if ((opts.subject || "").trim() === PA_SUBJECT) return true;
  return /^To:\s*\{\{\s*teams_target_email\s*\}\}/i.test((opts.bodyPlain || "").trim());
}
