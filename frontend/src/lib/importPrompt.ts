/** The copy-paste research prompt shown in the Import tab. `[COMPANY]` is filled with the
 *  current root. The news window is derived from the app's news-recency setting so the LLM
 *  gets concrete dates (and the current year) instead of a vague "recent" — works with any
 *  LLM (ChatGPT, Gemini, Claude, …). */
export function llmPrompt(
  company: string,
  opts: { recencyDays?: number; now?: Date } = {},
): string {
  const c = company || '[COMPANY]';
  const recencyDays = opts.recencyDays ?? 90;
  const now = opts.now ?? new Date();
  const today = now.toISOString().slice(0, 10);
  const from = new Date(now.getTime() - recencyDays * 86_400_000).toISOString().slice(0, 10);
  return `Research ${c} and its business relationships with other companies, based on real news published between ${from} and ${today} (about the last ${recencyDays} days). Today is ${today}. Output ONLY a single JSON object — no prose, no code fences — in exactly this shape:

{
  "name": "<short label>",
  "as_of": "${today}",
  "nodes": [
    { "id": "<ticker if public, else short name>", "label": "<display name>",
      "kind": "company|private_company|product|person|sector" }
  ],
  "edges": [
    { "source": "<node id>", "target": "<node id>",
      "type": "supplier|customer|partner|competitor|owner|subsidiary|other",
      "sentiment": "positive|negative|neutral", "weight": 0.0, "confidence": 0.0,
      "evidence": "<short fact or quote>", "url": "<source url>" }
  ]
}

Rules:
- Use the official stock ticker as "id" for any public company (e.g. NVDA, AAPL); a short readable id otherwise.
- "type" is the target's role relative to the source. Use "other" if none of the six fit.
- "sentiment" = the event's likely effect on the source company.
- "weight" = how material the relationship is (0-1); "confidence" = how sure you are it is real and current (0-1).
- Include only relationships supported by real information dated on or after ${from}; add a source "url" where possible.`;
}
