# DHT Analyzer EN — for Saleae Logic 2

A **High Level Analyzer (HLA)** extension that decodes the **DHT11 / DHT12 / DHT22 (AM2302)**
single-wire temperature & humidity protocol and prints the result as a bubble directly on the
waveform:

```
START 20.049 ms   →   RESPONSE 210.0 us   →   RH 33.0%  /  T 28.0 C
```

This is the **English build** of the DHT Analyzer extension. It is installed under a different
display name (`DHT Analyzer EN`), so it can live side by side with the Chinese build in the same
Logic 2 installation.

---

## 1. Requirements

* **Saleae Logic 2** (tested on **2.4.46**; requires the Extensions / HLA API)
* Any Saleae device (verified with **Logic 16**)
* Sample rate **≥ 4 MS/s** (the narrowest pulse is 27 µs; 10–25 MS/s recommended)

## 2. Installation

Copy this directory into your Logic 2 user extensions folder, then **restart Logic 2**
(extensions are scanned at startup):

```
%USERPROFILE%\Documents\Logic\High Level Analyzers\DHT Analyzer EN\
```

Alternative: in Logic 2 open the **Extensions** panel → three-dot menu → **Load Existing
Extension…** → select this folder's `extension.json`.

> If you change the Python code while Logic 2 is running, use **Reload Source Files** in the
> extension's three-dot menu instead of restarting.

## 3. Usage (2 analyzers)

A Logic 2 HLA can only take **another low-level analyzer** as its input — it cannot attach to a
digital channel directly. DHT is a pulse-width encoded protocol and none of the built-in
analyzers decodes pulse widths, so this extension **borrows the built-in Simple Parallel
analyzer as an edge sampler**.

> Once both analyzers are added, they persist across captures in the same session, so this is a
> one-time job per session.

1. Add **Simple Parallel** (analyzers panel → `+` → *Simple Parallel*):

   | Setting | Value |
   |---|---|
   | Clock Channel | the DHT data line |
   | Clock Edge | **Falling** |
   | D0 | **the same** DHT line |
   | D1 … D15 | `None` |

2. Add **DHT Analyzer EN** (`+` → *DHT Analyzer EN*) and set **Input Analyzer = Simple Parallel**.

   ⚠ If the Clock Channel is left unset, Simple Parallel produces no frames and the HLA stays
   **silently empty** (no error, empty data table). Edge markers + a green check + terminal
   init lines but no decoded frames ⇒ re-check the clock channel.

3. Sample rate ≥ 4 MS/s, trigger on a **falling edge** of that channel, and capture one read.
   A complete frame takes ≈ **24 ms**, so capture 50–100 ms after the trigger.

### Settings (only "Sensor Type" is normally needed)

| Setting | Default | Meaning |
|---|---|---|
| Sensor Type | `DHT11` | `DHT11` / `DHT12` / `DHT22 / AM2302` (different byte layout) |
| Start Interval Min (us) | `0` → **auto 500** | Edges farther apart than this start a new frame |
| Bit Low Width (us) | `0` → **auto 50** | Low time between bits (nominal 50 µs) |
| Bit 1 Threshold (us, high) | `0` → **auto 40** | High time above this = bit 1 (0 ≈ 27 µs, 1 ≈ 70 µs) |
| Show Bit Frames | `No` | One bubble per bit — useful when debugging timing |

`0` means *automatic*: Logic 2 initializes numeric settings to `min_value` (this API version has
no default support), so `min_value = 0` is used as the "auto" sentinel and the built-in
thresholds of the selected sensor type are applied.

## 4. Protocol reference

| Phase | Level | Duration |
|---|---|---|
| Host start | LOW | **≥ 18 ms** (20 ms typical) |
| After host release | HIGH | 20–40 µs |
| Sensor response | LOW / HIGH | **80 µs** each |
| Inter-bit gap | LOW | **~50 µs** (constant) |
| Bit `0` | HIGH | 26–28 µs |
| Bit `1` | HIGH | **~70 µs** |

One frame = start + response + **40 bits**:
`humidity integer / humidity decimal / temperature integer / temperature decimal / checksum`,
where `checksum = (b0 + b1 + b2 + b3) & 0xFF`.

Decoding uses the **time between adjacent falling edges** and compares each bit's high time
against the (constant) inter-bit low time, so it is insensitive to sample rate, wire length and
pull-up strength.

## 5. Known limitations

* The **last bit (bit 39) is not measurable** — there is no falling edge after it. It is the
  **LSB of the checksum**, so humidity & temperature (bytes 0–3) are still complete and the
  checksum is compared on its upper 7 bits only (the terminal notes `LSB unmeasurable`).
* If the capture ends before the last falling edge (≈ **24.1 ms** after the start), the reading
  is emitted as soon as **32 bits** are available (bytes 0–3 complete) and the checksum
  comparison is skipped. Extend the capture to 50–100 ms to get the checksum too.

## 6. Troubleshooting

| Symptom | Check |
|---|---|
| No bubbles at all | Simple Parallel Clock Channel set? Edge = Falling? D0 = the same line? |
| Only `START`, no `RESPONSE` | Sample rate too low, or the sensor did not answer (4.7 kΩ pull-up, VCC/GND, wiring) |
| Values look wrong | Wrong Sensor Type (DHT11 = 1 byte, DHT22 = 16-bit / 0.1) |
| Checksum mismatch | Turn on *Show Bit Frames* and inspect pulse widths; adjust *Bit Low Width* / *Bit 1 Threshold* |

The plugin prints to the Logic 2 terminal, e.g.

```
[DHT HLA EN] sensor=DHT11; thresholds start_min=500us bit_low=50us bit1>40us (auto)
[DHT HLA EN] raw=21 00 1C 00 (chk~3C / exp 3D, LSB unmeasurable) OK
```

## 7. License

MIT — see [LICENSE](LICENSE).
