# Hyprland VFR investigation

Read-only investigation, 2026-11-14. No configuration changes, reloads, GUI launches, package installs, or treatment benchmarks were performed.

## Conclusion

`debug.vfr = false` disables Hyprland's demand-driven frame scheduling optimization, **not** monitor Adaptive Sync. On the running DRM backend it requests another frame after each completed normal render. This can keep frame processing/commits running on an otherwise static desktop. It does **not** disable damage tracking or necessarily redraw every pixel, rerun every blur pass, or drive the GPU at 100%. Upstream defaults VFR to `true` and explicitly says not to turn it off unless debugging. Restoring that default is worth a controlled test, but this investigation does not establish savings or justify changing settings without approval. [1–3]

## Declared versus running state

Repository declaration: `modules/home/nixos/hyprland/settings.nix`, under the Lua `config` attrset. Live queries matched the relevant declared values:

| Setting | Declared | Live (`hyprctl getoption`) |
| --- | --- | --- |
| `debug:vfr` | `false` | `bool: false`, `set: true` |
| `render:direct_scanout` | `0` | `int: 0`, `set: true` |
| `cursor:no_hardware_cursors` | `2` | `int: 2`, `set: true` |
| `decoration:blur:size` / `passes` | `8` / `3` | `8` / `3`, both set |
| `decoration:active_opacity` / `inactive_opacity` | `0.94` / `0.90` | `0.940000` / `0.900000`, both set |
| `misc:vrr` | Not in this settings module | `int: 0`, `set: false` |
| `debug:damage_tracking` | Not in this settings module | `int: 2`, `set: false` |

Version evidence:

- `hyprctl version`: **0.57.0**, commit **`4c3a8fe81feea899c894faec50e10cf01b301d2f`**, tag `v0.57.0`, date `2026-11-09`, flags `nix`; reports **dirty**. Exact upstream source is therefore a strong reference, not proof that the packaged binary has no patches.
- `hyprctl status`: `configProvider: lua`, `backend: drm`.
- Current working-tree `flake.lock`: Hyprland **`0767f6347a69607638a4f93b3cd613af15a121e0`**, `lastModified = 1794583226` (**2026-11-13 15:20:26 UTC**). This is newer than the running compositor, not evidence it has been deployed. The VFR default and rescheduling condition are unchanged in the inspected pinned source. [4]
- `hyprctl configerrors`: empty output.

`hyprctl -j monitors` reported two enabled, DPMS-on 3840×2160 outputs at scale ~1.3333: DP-1 at 120 Hz, DP-2 at ~60 Hz (rotated). Both reported `vrr: false`, `directScanoutTo: "0"`, direct-scanout blockers `USER` and `CANDIDATE`, and `hardwareCursorsInUse: true`. DP-1 reported VRR capable; DP-2 did not. This is an instantaneous observation, not a measured compositor frame rate.

## What the exact source establishes

1. **VFR off means self-rescheduling, with qualifications.** `Renderer.cpp:2506–2507` calls `scheduleFrame` when `*PVFR == 0`. `CMonitor::scheduleFrame` forwards to Aquamarine, whose pinned DRM implementation sets `needsFrame = true` and queues/coalesces frame events. This is an output-paced loop, not an unconditional busy-spin. Inactive sessions, disabled outputs, commit coordination, and other early exits still apply. [1–3]
2. **Damage tracking remains separate.** The renderer checks pending frame/damage state before rendering; scene drawing is guarded by nonempty `finalDamage`. Empty-damage frames can instead send frame callbacks. Thus “continuous rendering” is fair shorthand for continuing normal frame processing here, but “full desktop redraw at 120/60 FPS” is not established. Blur/transparency affect damaged-scene cost; their current settings do not prove blur work occurs on every idle frame. [1]
3. **Direct scanout is independent.** Its own option defaults to `0`; `CMonitor::isDSBlocked` marks that as a user blocker. Successful direct scanout returns before the normal renderer's VFR rescheduling tail. VFR can conserve compositing work with scanout disabled; enabling scanout is not a prerequisite and should not be bundled into a VFR test. [1–2]
4. **VRR is independent.** `misc:vrr` controls display Adaptive Sync, with default `0`. VFR controls whether Hyprland asks for another frame; it does not set the physical monitor's adaptive-refresh policy. Current live VRR is off on both outputs. [2,5]
5. **Cursor value `2` is auto, not forced software cursors.** The running source selects software cursors in auto mode for NVIDIA with multi-GPU or active VRR; the live output actually reports hardware cursors on both displays. No cursor change is warranted from this value alone. [2]

## Why might the override exist?

Read-only history gives a deliberate choice but **no documented symptom or hardware-specific rationale**:

- `git show ad61f8c`: `fix(hyprland): disable variable frame rate`, changing `misc.vfr` from true to false in `modules/home/hyprland.nix`.
- `git show 3b1aa34`: preserves false while moving the option to `debug` for 0.55.
- Later split/unification and Lua migration retain it (`95729c7`, `b489be3`). The present comment explains the namespace move, not the reason for disabling VFR.

There is historical precedent for disabling VFR as a workaround: an upstream **0.35.0** report describes stale Kitty/Firefox contents until mouse movement, with disabling VFR or scaling as workarounds, and notes increased idle load. That establishes a plausible class of old damage/scheduling problems, **not** that this machine suffered it or that 0.57 still needs the workaround. [6]

GitHub issue searches for `repo:hyprwm/Hyprland "vfr" "0.57"`, `"vfr" "freeze"`, and `"vfr" "false" is:issue` were inspected; no matching 0.57-specific justification for this host was established. Search results and closed historical reports cannot prove absence of a regression. With the running/pinned version mismatch and dirty build flag, retest the actual deployed version before concluding the override is obsolete.

## Passive performance evidence and limitations

`amdgpu_top 0.11.4` is installed; its help warns that reading performance counters can deactivate GPU power saving. Only `--help` was run, not its sampler/TUI. No `pidstat`, `intel_gpu_top`, `radeontop`, `nvidia-smi`, `powertop`, `turbostat`, or `perf` was found on PATH. `/sys/class/power_supply` had no entries.

A Python read-only snapshot of sysfs, then `time.sleep(5)`, then another snapshot observed:

| Counter | First | Five seconds later |
| --- | --- | --- |
| `card1/device/gpu_busy_percent` | 11% | 11% |
| `card1/device/mem_busy_percent` | 1% | 2% |
| `card1/device/hwmon/hwmon1/power1_average` | 46,000,000 µW | 47,000,000 µW |
| `card0/device/gpu_busy_percent` | 0% | 0% |

Both cards reported AMD vendor `0x1002`; card1 resolves to PCI `0000:03:00.0`. These are **two device-wide snapshots during the existing session, not a controlled idle baseline**, not compositor-only energy consumption, and not proof of VFR causation. The hwmon power values use the standard microwatt ABI. [7] The visible `/proc`/`ps` namespace exposed no Hyprland process, so attempted process CPU accounting yielded no samples. No reliable frame-count or wall-power comparison was obtained. **No energy-saving percentage can be claimed.**

## Minimal follow-up — approval required, not executed

1. Ask whether false originally fixed stale windows, cursor responsiveness, flicker, fullscreen/game/video pacing, or multi-monitor freezes. Keep a known recovery route and record the exact deployed version; do not combine this with the pending flake update.
2. On a genuinely static desktop, capture repeated 30–60-second baseline windows with VFR false. Keep outputs, refresh rates, applications, cursor position, shell widgets, and power state identical; avoid animated terminals, overlays, screen recording, and frequent `hyprctl` polling. Use passive sysfs GPU/power samples; use host-visible `/proc` accounting if available. A wall meter is needed for whole-system power claims.
3. Only after explicit approval, test **VFR true alone** using the installed version's supported configuration interface; leave scanout, VRR, cursors, blur, and opacity unchanged. Verify the live value, repeat baseline/treatment/baseline to reduce drift, and record medians/ranges rather than isolated readings. Restore false immediately if correctness regresses; any permanent removal needs separate approval.
4. Check desktop idle-to-interaction, typing/caret updates, workspace animations, both monitors, browser/video and fullscreen transitions. Correctness takes priority over lower counters. If symptoms recur, document their exact reproducer/version instead of disabling damage tracking or making unrelated changes.

## Reproduction commands (all read-only)

```sh
hyprctl version
hyprctl status
hyprctl configerrors
hyprctl -j monitors
for opt in debug:vfr render:direct_scanout cursor:no_hardware_cursors \
  decoration:blur:size decoration:blur:passes decoration:active_opacity \
  decoration:inactive_opacity misc:vrr debug:damage_tracking; do
  printf '\n%s\n' "$opt"
  hyprctl getoption "$opt"
done
git log --all --oneline -G 'vfr' -- '*.nix'
git show ad61f8c --
git show 3b1aa34 --
amdgpu_top --help
```

`getoption` worked with this running Lua provider, so no Lua REPL fallback was necessary. Upstream files below were retrieved through read-only HTTPS requests at the exact revisions; no checkout or Nix evaluation/build was needed for this documentation-only investigation.

## Primary sources

1. [Running revision: renderer](https://github.com/hyprwm/Hyprland/blob/4c3a8fe81feea899c894faec50e10cf01b301d2f/src/render/Renderer.cpp#L2250-L2521): frame gates, direct-scanout early return, damaged-scene drawing, VFR rescheduling; also `shouldRenderMonitor` at lines 325–333.
2. Running revision: [option definitions](https://github.com/hyprwm/Hyprland/blob/4c3a8fe81feea899c894faec50e10cf01b301d2f/src/config/values/ConfigValues.cpp#L565-L758) and [monitor implementation](https://github.com/hyprwm/Hyprland/blob/4c3a8fe81feea899c894faec50e10cf01b301d2f/src/output/Monitor.cpp) (`scheduleFrame`: 1073–1084; `isDSBlocked`: 1901 onward; cursor auto: 2199–2217).
3. [Running revision's Aquamarine lock](https://github.com/hyprwm/Hyprland/blob/4c3a8fe81feea899c894faec50e10cf01b301d2f/flake.lock) pins `eac1b827c4a12dc026f21c966cde2f248fe6ee12`; its [DRM scheduleFrame implementation](https://github.com/hyprwm/aquamarine/blob/eac1b827c4a12dc026f21c966cde2f248fe6ee12/src/backend/drm/DRM.cpp#L3012-L3053). Runtime reports Aquamarine 0.15.1; packaged dependency patches were not audited.
4. Current flake pin: [renderer rescheduling](https://github.com/hyprwm/Hyprland/blob/0767f6347a69607638a4f93b3cd613af15a121e0/src/render/Renderer.cpp#L2536-L2539), [VFR option default](https://github.com/hyprwm/Hyprland/blob/0767f6347a69607638a4f93b3cd613af15a121e0/src/config/values/ConfigValues.cpp#L758).
5. [Official configuration reference](https://github.com/hyprwm/hyprland-wiki/blob/main/content/configuring/core/config-options.md), retrieved via Context7; current documentation is supporting context, not a substitute for the pinned source.
6. [Historical upstream stale-frame/workaround report](https://github.com/hyprwm/Hyprland/issues/3778#issuecomment-1962978314), explicitly 0.35.0, not a verified 0.57 defect.
7. [Linux hwmon ABI](https://docs.kernel.org/hwmon/sysfs-interface.html): `power*_average` is average power use in microwatts; sensor scope/averaging does not make it whole-system power.
