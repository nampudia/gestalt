#!/usr/bin/env python3
"""
Screentest film understanding layer.

Turns a video file into film.json: scenes with titles and one-line captions,
plus a dialogue transcript, so the Audience notes can talk about
"the mine-cart ride" instead of "1:04".

    export ANTHROPIC_API_KEY=sk-ant-...        # from platform.claude.com
    python3 analyze_film.py caminandes.mp4 --title "Caminandes 3: Llamigos"

Steps
  1. Scene split   ffmpeg finds every cut, then short shots are grouped into scenes.
  2. Transcript    faster-whisper transcribes dialogue (optional: pip install faster-whisper).
  3. Captions      Claude looks at 3 frames per scene (+ its dialogue) and names it.

Needs: ffmpeg on your PATH (brew install ffmpeg). No Python packages are required
for steps 1 and 3; step 2 is skipped if faster-whisper isn't installed.
"""
import argparse, base64, json, os, re, subprocess, sys, tempfile, urllib.request

MODEL = os.environ.get("SCREENTEST_MODEL", "claude-sonnet-5-5")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path])
    return float(r.stdout.strip())


def detect_cuts(path, threshold):
    """Timestamps where the picture changes sharply (camera cuts)."""
    r = run(["ffmpeg", "-hide_banner", "-i", path, "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"])
    return [float(x) for x in re.findall(r"pts_time:([0-9.]+)", r.stderr)]


def group_scenes(cuts, total, min_len):
    """Merge rapid-fire shots so each scene is at least min_len seconds."""
    bounds = [0.0] + [c for c in cuts if 0.5 < c < total - 0.5] + [total]
    scenes, start = [], bounds[0]
    for b in bounds[1:]:
        if b - start >= min_len or b == total:
            scenes.append([start, b]); start = b
    if len(scenes) > 1 and scenes[-1][1] - scenes[-1][0] < min_len / 2:
        scenes[-2][1] = scenes[-1][1]; scenes.pop()
    return scenes


def frames_b64(path, start, end, n=3):
    out = []
    with tempfile.TemporaryDirectory() as d:
        for i in range(n):
            t = start + (end - start) * (i + 0.5) / n
            f = os.path.join(d, f"{i}.jpg")
            run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", "scale=512:-2", "-q:v", "5", f])
            if os.path.exists(f):
                out.append(base64.b64encode(open(f, "rb").read()).decode())
    return out


def transcribe(path):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("  faster-whisper not installed, skipping transcript (pip install faster-whisper)")
        return []
    print("  transcribing (first run downloads the model)...")
    model = WhisperModel("small", device="auto", compute_type="int8")
    segs, _ = model.transcribe(path, vad_filter=True)
    return [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]


def claude(content, key, max_tokens=400):
    body = json.dumps({"model": MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    return "".join(b.get("text", "") for b in data.get("content", []))


def caption_scene(path, sc, lines, title, key, idx, total):
    imgs = frames_b64(path, sc["start"], sc["end"])
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}} for b in imgs]
    said = " ".join(l["text"] for l in lines) or "(no dialogue)"
    content.append({"type": "text", "text": (
        f'These are 3 frames from scene {idx+1} of {total} of the film "{title}", '
        f'running {sc["start"]:.0f}s to {sc["end"]:.0f}s. Dialogue in this scene: {said}\n\n'
        'Reply with only JSON: {"title": "2 to 4 word scene name a film editor would use", '
        '"caption": "one plain sentence on what happens", '
        '"tone": "one of comedy, tension, action, emotional, quiet, credits"}')})
    txt = claude(content, key)
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {"title": f"Scene {idx+1}", "caption": txt.strip()[:160], "tone": "quiet"}


def main():
    ap = argparse.ArgumentParser(description="Build film.json (scenes, captions, transcript) for Screentest.")
    ap.add_argument("video")
    ap.add_argument("--title", default=None)
    ap.add_argument("--out", default="film.json")
    ap.add_argument("--threshold", type=float, default=0.3, help="cut sensitivity, lower finds more cuts")
    ap.add_argument("--min-scene", type=float, default=10, help="shortest scene in seconds")
    ap.add_argument("--no-transcript", action="store_true")
    a = ap.parse_args()

    key = os.environ.get("ANTHROPIC_API_KEY")
    title = a.title or os.path.splitext(os.path.basename(a.video))[0]
    total = duration(a.video)
    print(f"{title}: {total/60:.1f} min")

    print("1/3 finding scenes...")
    scenes = [{"start": round(s, 2), "end": round(e, 2)} for s, e in group_scenes(detect_cuts(a.video, a.threshold), total, a.min_scene)]
    print(f"  {len(scenes)} scenes")

    print("2/3 transcript...")
    transcript = [] if a.no_transcript else transcribe(a.video)
    for sc in scenes:
        sc["lines"] = [l for l in transcript if sc["start"] <= l["start"] < sc["end"]]

    print("3/3 captions...")
    for i, sc in enumerate(scenes):
        if key:
            try:
                sc.update(caption_scene(a.video, sc, sc["lines"], title, key, i, len(scenes)))
                print(f"  {sc['start']:6.0f}s  {sc['title']}: {sc['caption']}")
                continue
            except Exception as e:
                print(f"  scene {i+1}: Claude call failed ({e}), using a placeholder")
        sc.update({"title": f"Scene {i+1}", "caption": "", "tone": "quiet"})
    if not key:
        print("  no ANTHROPIC_API_KEY set, scenes are unnamed. Set it and rerun for captions.")

    for sc in scenes:
        sc["dialogue"] = " ".join(l["text"] for l in sc.pop("lines"))
    json.dump({"title": title, "duration": round(total, 2), "scenes": scenes, "transcript": transcript,
               "generated_by": {"scenes": "ffmpeg", "transcript": "faster-whisper" if transcript else None, "captions": MODEL if key else None}},
              open(a.out, "w"), indent=2)
    print(f"Saved {a.out}")


if __name__ == "__main__":
    main()
