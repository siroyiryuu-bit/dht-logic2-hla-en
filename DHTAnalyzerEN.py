# -*- coding: utf-8 -*-
"""
DHT-family single-wire temperature & humidity protocol decoder
(Saleae Logic 2 · High Level Analyzer · English build)

Supports DHT11 / DHT12 / DHT22(AM2302) — picking the sensor type fills in every
timing threshold automatically, no manual setup needed.

============================== HOW TO USE (READ ME) ==============================
In Logic 2 a High Level Analyzer can only take *another low-level analyzer* as its
input — it cannot attach to a digital channel directly. DHT is a pulse-width encoded
single-wire protocol and none of the built-in analyzers is a pulse-width decoder, so
this plugin borrows the built-in **Simple Parallel** analyzer as an *edge sampler*:

  1) Add a Simple Parallel analyzer and set:
       · Clock Channel = the channel the DHT data line is on
       · Clock Edge    = Falling
       · D0            = the same DHT data line (set D1..D15 to None)
       · Sample rate >= 4 MS/s (narrowest pulse is 27 us; 10-25 MS/s recommended)
  2) Add this HLA (DHT Analyzer EN) and set "Input Analyzer" to that Simple Parallel.
  3) Only "Sensor Type" needs to be chosen (DHT11 / DHT12 / DHT22-AM2302); all timing
     thresholds are derived from the type. The three numeric settings default to
     0 = auto and normally need no attention.

============================== ABOUT DEFAULTS ==============================
In this Logic 2 build `saleae.analyzers.settings` cannot carry per-setting defaults
(`Setting.__init__` only accepts a label; `_serialize` does not emit `default`), and
the UI fills numeric settings with `min_value`. This plugin therefore sets
`min_value = 0` for the three numeric settings and defines **0 = auto**: the built-in
thresholds for the selected sensor type are applied and nothing has to be typed.

============================== DECODING PRINCIPLES ==============================
Simple Parallel emits one frame per falling edge. For a single DHT read the falling
edges are:

    F1 = host pulls the line low (start)   F2 = sensor response low
    F3..F42 = the "inter-bit low" of the 40 data bits

Time between adjacent falling edges:

    F1->F2 ~= 20 ms + 80 us      -> start of frame (far longer than anything else,
                                    which is what we use for synchronization)
    F2->F3 ~= 80 + 80 + 50       -> sensor response (about 210 us)
    F(n)->F(n+1) = high time + 50 us -> data bit: 77 us = 0, 120 us = 1

Bit value = whether (interval - inter-bit low width) exceeds the "1" threshold.

Note: the high time of the very last bit (bit 39) has no falling edge after it, and
that bit is the **LSB of the checksum byte**, so it cannot be measured. Fortunately
the first four bytes (humidity / temperature) are complete, so the checksum is
compared ignoring that LSB (and the result says so).

Debugging: `print()` output shows up in the Logic 2 Terminal.
"""

from saleae.analyzers import HighLevelAnalyzer, AnalyzerFrame, NumberSetting, ChoicesSetting


class DhtHlaEn(HighLevelAnalyzer):
    """DHT11 / DHT12 / DHT22(AM2302) single-wire protocol decoder (English build)"""

    # ---------------- settings ----------------
    # Numeric settings use min_value=0 and **0 means "auto by sensor type"**
    # (Logic 2 initializes numeric settings to min_value, so "auto" is the default).
    sensor_type = ChoicesSetting(
        label='Sensor Type',
        choices=('DHT11', 'DHT12', 'DHT22 / AM2302'))
    start_min_us = NumberSetting(
        label='Start Interval Min (us) [0=auto]', min_value=0, max_value=50000)
    bit_low_us = NumberSetting(
        label='Bit Low Width (us) [0=auto]', min_value=0, max_value=200)
    bit_one_us = NumberSetting(
        label='Bit 1 Threshold (us, high) [0=auto]', min_value=0, max_value=200)
    show_bit_frames = ChoicesSetting(
        label='Show Bit Frames', choices=('No', 'Yes'))

    # ---------------- built-in timings per sensor type (applied automatically) ----------------
    # The same three values work for every DHT variant: the inter-bit low is nominally
    # 50 us and a bit high time is ~27 us for a 0 and ~70 us for a 1 (threshold 40 us).
    # start_min only has to be larger than the longest non-start interval (the response,
    # ~210 us) and smaller than the start interval (DHT11 ~20 ms, DHT22 ~1.1 ms),
    # so 500 us is valid for all types.
    AUTO = {
        'start_min_us': 500.0,
        'bit_low_us': 50.0,
        'bit_one_us': 40.0,
    }

    # ---------------- output frame types ----------------
    result_types = {
        'dht_start': {
            'format': 'START  {{data.duration}}'
        },
        'dht_response': {
            'format': 'RESPONSE  {{data.duration}}'
        },
        'dht_data': {
            'format': 'RH {{data.humidity}}%  /  T {{data.temperature}} C'
        },
        'dht_error': {
            'format': 'ERR  {{data.info}}'
        },
        'dht_bit': {
            'format': 'bit{{data.index}}={{data.value}} ({{data.high_us}}us)'
        },
    }

    # ---------------- init ----------------
    def __init__(self):
        # Effective thresholds: a non-zero setting wins, 0 (the default) means auto.
        self.eff_start_min = self._pick(self.start_min_us, self.AUTO['start_min_us'])
        self.eff_bit_low = self._pick(self.bit_low_us, self.AUTO['bit_low_us'])
        self.eff_bit_one = self._pick(self.bit_one_us, self.AUTO['bit_one_us'])

        self.prev_time = None      # previous falling edge
        self.state = 'idle'        # idle -> response -> bits
        self.bits = []             # [(value, high_us, start_time, end_time), ...]
        self.bits_start_time = None
        self.emitted = False       # reading bubble already emitted for the current frame

        print('[DHT HLA EN] sensor=%s; thresholds start_min=%.0fus bit_low=%.0fus bit1>%.0fus (%s)'
              % (self.sensor_type, self.eff_start_min, self.eff_bit_low,
                 self.eff_bit_one,
                 'manual' if self.start_min_us else 'auto'))

    @staticmethod
    def _pick(value, auto_value):
        """0 or invalid -> use the automatic value."""
        try:
            v = float(value)
        except Exception:
            return auto_value
        return v if v > 0 else auto_value

    # ---------------- helpers ----------------
    @staticmethod
    def _delta_us(t0, t1):
        """Difference of two SaleaeTime values in microseconds."""
        try:
            return float(t1 - t0) * 1e6
        except Exception:
            try:
                return (float(t1) - float(t0)) * 1e6
            except Exception:
                return None

    @staticmethod
    def _fmt(us):
        if us is None:
            return '?'
        if us < 1000.0:
            return '%.1f us' % us
        return '%.3f ms' % (us / 1000.0)

    def _reset(self):
        self.state = 'idle'
        self.bits = []
        self.bits_start_time = None
        self.emitted = False

    # ---------------- decoding ----------------
    def decode(self, frame: AnalyzerFrame):
        try:
            return self._decode(frame)
        except Exception as e:      # never let an exception take the whole HLA down
            print('[DHT HLA EN] decode exception: %r' % (e,))
            return None

    def _decode(self, frame: AnalyzerFrame):
        t = frame.start_time
        if self.prev_time is None:
            self.prev_time = t
            return None

        dt = self._delta_us(self.prev_time, t)
        t0 = self.prev_time
        self.prev_time = t
        if dt is None:
            return None

        # ---- an over-long interval marks the start of a new frame ----
        if dt >= self.eff_start_min:
            out = []
            if self.state == 'bits' and self.bits:
                if self.emitted:
                    pass          # the reading was already emitted for this frame
                elif len(self.bits) >= 32:
                    # the previous frame is complete except for the checksum bits
                    out.extend(self._finish(t0, len(self.bits) >= 39))
                else:
                    out.append(AnalyzerFrame(
                        'dht_error', self.bits_start_time, t0,
                        {'info': 'incomplete frame: only %d bits' % len(self.bits)}))
            self._reset()
            self.state = 'response'
            out.append(AnalyzerFrame('dht_start', t0, t,
                                     {'duration': self._fmt(dt)}))
            return out

        # ---- the first interval after the start is the sensor response ----
        if self.state == 'response':
            self.state = 'bits'
            self.bits = []
            self.bits_start_time = t
            return [AnalyzerFrame('dht_response', t0, t,
                                  {'duration': self._fmt(dt)})]

        # ---- data bits ----
        if self.state == 'bits':
            high = dt - self.eff_bit_low
            bit = 1 if high > self.eff_bit_one else 0
            idx = len(self.bits)                    # 0..38 (bit 39 is not measurable)
            self.bits.append((bit, high, t0, t))

            if self.show_bit_frames == 'Yes':
                return [AnalyzerFrame('dht_bit', t0, t, {
                    'index': idx,
                    'value': bit,
                    'high_us': '%.0f' % high,
                })]

            out = []
            # Emit the reading as soon as 32 bits are in (bytes 0..3 are complete) so that
            # a capture ending right before the last falling edge (~24.1 ms) still
            # produces output. Measured lesson: captures often end exactly there.
            if not self.emitted and len(self.bits) >= 32:
                out.extend(self._finish(t, False))
                self.emitted = True
            # Keep collecting the remaining checksum bits. NOTE: this must NOT be an
            # `elif` — the early emit above used to shadow this branch, which meant the
            # checksum was never verified (every result read "checksum pending").
            if len(self.bits) >= 39:
                if self.emitted:
                    out.extend(self._checksum_only(self.bits_start_time, t))
                else:
                    out.extend(self._finish(t, True))
                self._reset()
            if out:
                return out

        return None

    # ---------------- framing / checksum / reading ----------------
    def _bytes_and_checksum(self):
        """Return (b0, b1, b2, b3, expected_checksum, received_upper_7_bits)."""
        bits = [b[0] for b in self.bits]
        data = []
        for i in range(0, 39, 8):
            byte = 0
            for b in bits[i:i + 8]:
                byte = (byte << 1) | b
            data.append(byte)                        # first 4 bytes full, 5th has 7 bits
        while len(data) < 5:
            data.append(0)
        b0, b1, b2, b3 = data[0], data[1], data[2], data[3]
        return b0, b1, b2, b3, (b0 + b1 + b2 + b3) & 0xFF, data[4]

    def _read_values(self, b0, b1, b2, b3):
        """Per sensor type byte decoding."""
        if self.sensor_type == 'DHT22 / AM2302':
            humidity = float(((b0 << 8) | b1)) * 0.1
            raw_t = float(((b2 & 0x7F) << 8) | b3) * 0.1
            temperature = -raw_t if (b2 & 0x80) else raw_t
        else:                                        # DHT11 / DHT12
            humidity = float(b0) + float(b1) * 0.1
            temperature = float(b2) + float(b3) * 0.1
        return humidity, temperature

    def _checksum_info(self):
        """(ok, human readable line) for the checksum of the current frame."""
        b0, b1, b2, b3, expected, recv_top7 = self._bytes_and_checksum()
        # recv_top7 = the received checksum's upper 7 bits = checksum >> 1;
        # the LSB is unmeasurable (there is no falling edge after bit 39).
        ok = (recv_top7 == (expected >> 1))
        info = ('raw=%02X %02X %02X %02X (chk~%02X / exp %02X, LSB unmeasurable) %s'
                % (b0, b1, b2, b3, recv_top7 << 1, expected, 'OK' if ok else 'BAD'))
        return ok, info

    def _finish(self, end_time, checksum_known):
        """Assemble the frame.

        checksum_known=True  -> all 39 intervals arrived: verify and report the checksum.
        checksum_known=False -> early emit at 32 bits: the reading is valid, the verdict
                                is printed later by _checksum_only()."""
        b0, b1, b2, b3, _expected, _recv = self._bytes_and_checksum()
        humidity, temperature = self._read_values(b0, b1, b2, b3)
        span_start = self.bits_start_time

        if checksum_known:
            ok, info = self._checksum_info()
        else:
            ok = None
            info = ('raw=%02X %02X %02X %02X (%d bits -> RH/T valid, checksum pending)'
                    % (b0, b1, b2, b3, len(self.bits)))
        print('[DHT HLA EN] %s' % info)

        # Only a definite checksum failure becomes an error frame; a partial capture still
        # yields a valid reading.
        if ok is False:
            return [AnalyzerFrame('dht_error', span_start, end_time, {
                'info': 'checksum mismatch %s' % info})]
        return [AnalyzerFrame('dht_data', span_start, end_time, {
            'humidity': ('%.1f' % humidity),
            'temperature': ('%.1f' % temperature)})]

    def _checksum_only(self, span_start, end_time):
        """The reading was already emitted; report the checksum verdict only."""
        ok, info = self._checksum_info()
        print('[DHT HLA EN] %s' % info)
        if not ok:
            return [AnalyzerFrame('dht_error', span_start, end_time, {
                'info': 'checksum mismatch %s' % info})]
        return []
