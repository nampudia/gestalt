// POST /api/notes: sends the screening summary to Claude and returns audience notes.
// The API key lives only in Vercel's environment variables, never in the page.
const fs = require("fs");
const path = require("path");

const PROMPT = fs.readFileSync(path.join(process.cwd(), "notes_prompt.txt"), "utf8");
const MODEL = process.env.SCREENTEST_MODEL || "claude-sonnet-5-5";

function parseNotes(text) {
  let caveat = "";
  const m = text.match(/"caveat"\s*:\s*"((?:[^"\\]|\\.)*)"/);
  if (m) { try { caveat = JSON.parse('"' + m[1] + '"'); } catch (_) {} }
  try {
    const obj = JSON.parse(text.slice(text.indexOf("{"), text.lastIndexOf("}") + 1));
    if (obj && Array.isArray(obj.notes)) return { caveat: obj.caveat || caveat, notes: obj.notes };
  } catch (_) {}
  // Reply cut off: keep every complete note object.
  const notes = [];
  let i = text.indexOf("[");
  if (i < 0) throw new Error("Claude didn't return notes in the expected format");
  while ((i = text.indexOf("{", i + 1)) >= 0) {
    let depth = 0, inStr = false, esc = false, j = i;
    for (; j < text.length; j++) {
      const c = text[j];
      if (inStr) { if (esc) esc = false; else if (c === "\\") esc = true; else if (c === '"') inStr = false; continue; }
      if (c === '"') inStr = true; else if (c === "{") depth++; else if (c === "}" && --depth === 0) break;
    }
    if (j >= text.length) break;
    try { notes.push(JSON.parse(text.slice(i, j + 1))); } catch (_) {}
    i = j;
  }
  if (!notes.length) throw new Error("Claude didn't return notes in the expected format");
  return { caveat, notes };
}

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") return res.status(405).json({ error: "Use POST" });
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) return res.status(400).json({ error: "ANTHROPIC_API_KEY isn't set for this deployment" });
  const pass = process.env.NOTES_PASSCODE;
  if (pass && req.headers["x-screentest-pass"] !== pass) return res.status(401).json({ error: "Wrong passcode" });

  let payload = req.body;
  if (typeof payload === "string") { try { payload = JSON.parse(payload); } catch (_) { return res.status(400).json({ error: "Bad request" }); } }
  const data = JSON.stringify(payload || {});
  if (data.length > 400000) return res.status(413).json({ error: "Screening data too large" });

  try {
    const r = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json" },
      body: JSON.stringify({ model: MODEL, max_tokens: 8000, messages: [{ role: "user", content: PROMPT + "\n\nSCREENING DATA:\n" + data }] }),
    });
    const body = await r.json();
    if (!r.ok) return res.status(502).json({ error: `Claude API ${r.status}: ${JSON.stringify(body).slice(0, 300)}` });
    const text = (body.content || []).map(b => b.text || "").join("");
    const out = parseNotes(text);
    return res.status(200).json({ notes: out.notes, caveat: out.caveat, model: MODEL });
  } catch (e) {
    return res.status(500).json({ error: String(e.message || e).slice(0, 300) });
  }
};
