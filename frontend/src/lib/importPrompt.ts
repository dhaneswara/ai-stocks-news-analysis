/** The copy-paste prompt shown in the Import tab. `[COMPANY]` is filled with the current root. */
export function chatGptPrompt(company: string): string {
  const c = company || '[COMPANY]';
  return `Research ${c} and its business relationships with other companies, based on recent, real news. Output ONLY a single JSON object — no prose, no code fences — in exactly this shape:

{
  "name": "<short label>",
  "as_of": "<YYYY-MM-DD>",
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
- Include only relationships supported by real information; add a source "url" where possible.`;
}
