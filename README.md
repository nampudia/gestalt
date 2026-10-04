# Screentest

Audience reaction testing for films. Viewers get paid to watch a screening with their camera on; studios get a moment-by-moment timeline of laughs, gasps, tension, confusion and drift, a survey report broken down by audience group, and AI-written audience notes.

**Concept prototype.** Payouts aren't live, and there's no backend yet: everything runs in the browser plus a small local server.

## Run it

```bash
python3 serve.py                      # opens http://localhost:8000
```

For Claude-written Audience notes, set an API key from [platform.claude.com](https://platform.claude.com) first:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # never commit this
python3 serve.py
```

The key stays on your machine. The page calls `serve.py`, and only `serve.py` talks to the Claude API. Without a key, notes come from built-in rules.

Useful URLs:
- `/` viewer app (watch & earn)
- `/#studio` studio dashboard (invites, protection settings)
- `/?sample=1` sample 14-person screening with the full report
- `?demo=1` fake face tracking, for testing without a camera

## Understanding a film

`analyze_film.py` builds `film.json` (scenes, captions, transcript), so notes can talk about "the mine-cart ride" instead of "1:04".

```bash
brew install ffmpeg
pip install faster-whisper              # optional, for dialogue
export ANTHROPIC_API_KEY=sk-ant-...
python3 analyze_film.py my-cut.mp4 --title "My Film"
```

1. **Scenes:** ffmpeg finds every cut, then short shots are grouped into scenes.
2. **Transcript:** faster-whisper transcribes the dialogue.
3. **Captions:** Claude looks at 3 frames per scene, plus its dialogue, and names it.

## Files

| File | What it is |
|---|---|
| `index.html` | The whole app: viewer flow, studio, results editor, report |
| `serve.py` | Local server: video seeking, plus the `/api/notes` Claude proxy |
| `analyze_film.py` | Film understanding pipeline (scenes, Whisper, Claude captions) |
| `film.json` | Scene data for the sample film |
| `caminandes.mp4`, `poster.jpg` | Sample film, 720p |
| `prototypes/` | Earlier experiments (Python capture script, first dashboard) |

## How reactions are measured

MediaPipe Face Landmarker runs in the viewer's browser. No video leaves the device; only per-second numbers are saved:

- head pose and gaze, for attention
- blinks, for immersion
- 52 face blendshapes, compared against each viewer's own resting face: laughs, gasps (brow raise and jaw drop), tension (lip press), confusion (brow furrow), cringe (nose wrinkle)
- an end-of-film survey: recommend, theaters vs streaming, the ending, the moment that stuck, three words

## Not built yet

- Backend: accounts, hosted invites, results collected automatically (Supabase)
- DRM video hosting so screen recordings come out black (Mux or Bitmovin)
- Real payouts (Stripe Connect or PayPal Payouts)
- Next-day "what do you remember?" texts (Twilio)

## Credits

Sample film: *Caminandes 3: Llamigos* © Blender Foundation, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/).
