# Sheru listening-orb animations

Yash wants a Siri-style listening animation: tap mic → orb appears (audio-reactive); click orb → chat panel;
hold F5 → chat panel directly. Approaches A+E to build/try now; B and D stored for overnight builds.

## A + E — Core Animation, audio-reactive  ✅ built (preview)

`src/sheru/orb.py`. A borderless always-on-top `NSPanel` with a `CAGradientLayer` (radial) orb: gentle idle
"breathe" (`CABasicAnimation` on `transform.scale`, autoreverse ∞) plus live scaling from mic RMS (E). GPU-
composited, ~zero CPU. **Preview it:** `uv run python -m sheru.orb` (speak — it swells with your voice; click to
test the tap). Tune knobs: `ORB` size, gradient colors, glow (`setShadowRadius_/Opacity_`), `0.6 * level` gain,
breathe duration.

**Wiring once the look is approved (not done yet):**
- `activate()` (mic tap / F5 tap) → `orb.show()` + start the listen loop; drive `orb.set_level(rms)` from the
  capture loop (expose per-block RMS from `audio.capture_once`, like `orb._amp`).
- Orb `mouseDown_` → open the full `TypePanel` (chat).
- Listen ends → `orb.hide()`.
- **F5 tap-vs-hold:** measure key-down duration in the hotkey monitor — short = orb, long-hold = open chat
  directly. (Trigger currently fires on release via the Unix socket; add duration to distinguish.)

## B — Metal fluid blob (the premium look)  ⏳ overnight

The real Siri / ChatGPT flowing gradient mesh. `MTKView` (pyobjc `Metal`/`MetalKit`) + a fragment shader (MSL)
doing domain-warped simplex noise over a 2–3 stop gradient, `time` + audio amplitude as uniforms. Highest visual
quality; the hard part is writing/compiling the `.metal` shader and bridging `MTKViewDelegate.drawInMTKView_` in
pyobjc (sparse examples). Budget a focused overnight session. Fallback if pyobjc-Metal is too fiddly: render the
same shader in a `WKWebView` via a WebGL/three.js shader (allowed since it's local HTML), thinner but simpler.

## D — Particle swirl  ⏳ overnight

`CAEmitterLayer` with a soft circular `CAEmitterCell` (birthRate/velocity/lifetime), particles orbiting the
centre; drive `birthRate` + `velocity` from mic amplitude so it energizes as you speak. GPU, efficient, moderate
effort. Reads as "magic dust" rather than a solid orb — can be layered under A's orb for a hybrid.

## Decision log
- 2026-08-30: Yash chose **A+E** to build now, keep **B** and **D** as options / overnight builds. Style + color
  not finalized — current default is a blue→violet radial orb; awaiting his pick (orb / rings / bars / blob;
  Siri multicolor vs a single Sheru accent).
