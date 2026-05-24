/* depeg-monitor — analytics indicators.
 *
 * Plain functions. No deps. All take a `series` of `{t, price}` points (oldest
 * first) and return either a transformed `[{t, value}]` series (plottable as
 * an overlay) or an object of series. `value` is always in bps unless noted.
 *
 * Exposed on `window.depegIndicators` so the in-page sandbox can call them.
 */
(function () {
  // ---------------------------------------------------------------- primitives
  function bps(price, peg) {
    return ((price - peg) / peg) * 10000;
  }
  function asBps(series, peg) {
    return series.map(p => ({ t: p.t, value: bps(p.price, peg) }));
  }
  function clean(series) {
    return series.filter(p => Number.isFinite(p.price));
  }

  // ---------------------------------------------------------------- moving avg
  // Exponentially weighted moving average of price.
  // Returns series of {t, price: ewma} so it composes with other price-domain
  // helpers; pair with asBps to plot as bps-domain overlay.
  function ewma(series, opts) {
    const alpha = (opts && opts.alpha) != null ? opts.alpha : 0.2;
    const out = [];
    let prev = null;
    for (const p of clean(series)) {
      const v = prev == null ? p.price : alpha * p.price + (1 - alpha) * prev;
      out.push({ t: p.t, price: v });
      prev = v;
    }
    return out;
  }

  // ---------------------------------------------------------------- rolling
  // Generic rolling-window aggregator. `fn(windowArr)` runs on each window of
  // the last `win` prices and produces one number per tick (NaN until full).
  function rolling(series, win, fn) {
    const out = [];
    const buf = [];
    for (const p of clean(series)) {
      buf.push(p.price);
      if (buf.length > win) buf.shift();
      out.push({ t: p.t, value: buf.length < win ? NaN : fn(buf) });
    }
    return out;
  }

  // ---------------------------------------------------------------- z-score
  // Z-score of bps deviation against a rolling mean+stddev of bps.
  // Big absolute z = the current deviation is unusual relative to recent
  // history, even if absolute bps is small. Useful for sleepy pegs.
  function zscore(series, opts) {
    const peg = (opts && opts.peg) != null ? opts.peg : 1.0;
    const win = (opts && opts.win) || 20;
    const dev = clean(series).map(p => ({ t: p.t, v: bps(p.price, peg) }));
    const out = [];
    const buf = [];
    for (const p of dev) {
      buf.push(p.v);
      if (buf.length > win) buf.shift();
      if (buf.length < win) { out.push({ t: p.t, value: NaN }); continue; }
      const mean = buf.reduce((a, b) => a + b, 0) / buf.length;
      const variance = buf.reduce((a, b) => a + (b - mean) ** 2, 0) / buf.length;
      const sd = Math.sqrt(variance);
      out.push({ t: p.t, value: sd === 0 ? 0 : (p.v - mean) / sd });
    }
    return out;
  }

  // ---------------------------------------------------------------- volatility
  // Rolling stddev of log-returns, annualised assumption-free (raw bps).
  // High vol = peg is moving fast even if it hasn't broken yet.
  function volatility(series, opts) {
    const win = (opts && opts.win) || 20;
    const s = clean(series);
    const out = [];
    const buf = [];
    for (let i = 0; i < s.length; i++) {
      if (i === 0) { out.push({ t: s[i].t, value: NaN }); continue; }
      const ret = (s[i].price - s[i - 1].price) / s[i - 1].price;
      buf.push(ret);
      if (buf.length > win) buf.shift();
      if (buf.length < win) { out.push({ t: s[i].t, value: NaN }); continue; }
      const mean = buf.reduce((a, b) => a + b, 0) / buf.length;
      const variance = buf.reduce((a, b) => a + (b - mean) ** 2, 0) / buf.length;
      // Express as bps stddev so it overlays in the same y-domain.
      out.push({ t: s[i].t, value: Math.sqrt(variance) * 10000 });
    }
    return out;
  }

  // ---------------------------------------------------------------- drawdown
  // Running depeg depth from peg (negative-only): the worst |deviation| since
  // last full re-peg. Resets to 0 when price returns within `eps` bps of peg.
  function drawdown(series, opts) {
    const peg = (opts && opts.peg) != null ? opts.peg : 1.0;
    const eps = (opts && opts.eps) != null ? opts.eps : 5; // bps
    const out = [];
    let worst = 0;
    for (const p of clean(series)) {
      const b = bps(p.price, peg);
      if (Math.abs(b) < eps) worst = 0;
      else if (Math.abs(b) > Math.abs(worst)) worst = b;
      out.push({ t: p.t, value: worst });
    }
    return out;
  }

  // ---------------------------------------------------------------- bollinger
  // Bollinger bands of bps deviation. Returns {upper, lower, mean} — three
  // series, each plottable separately.
  function bollinger(series, opts) {
    const peg = (opts && opts.peg) != null ? opts.peg : 1.0;
    const win = (opts && opts.win) || 20;
    const k   = (opts && opts.k)   || 2;
    const dev = clean(series).map(p => ({ t: p.t, v: bps(p.price, peg) }));
    const upper = [], lower = [], mean = [];
    const buf = [];
    for (const p of dev) {
      buf.push(p.v);
      if (buf.length > win) buf.shift();
      if (buf.length < win) {
        upper.push({ t: p.t, value: NaN });
        lower.push({ t: p.t, value: NaN });
        mean.push({ t: p.t, value: NaN });
        continue;
      }
      const m = buf.reduce((a, b) => a + b, 0) / buf.length;
      const variance = buf.reduce((a, b) => a + (b - m) ** 2, 0) / buf.length;
      const sd = Math.sqrt(variance);
      upper.push({ t: p.t, value: m + k * sd });
      lower.push({ t: p.t, value: m - k * sd });
      mean.push({ t: p.t, value: m });
    }
    return { upper, lower, mean };
  }

  // ---------------------------------------------------------------- recovery
  // List of depeg events with recovery duration. An event begins when |bps|
  // crosses `threshold` and ends when it falls back below `eps` for at least
  // `coolDownTicks` consecutive ticks. Returns [{firstT, lastT, peakBps,
  // peakPrice, durationMs, recoveryMs}].
  function recoveryTime(series, opts) {
    const peg = (opts && opts.peg) != null ? opts.peg : 1.0;
    const threshold = (opts && opts.threshold) != null ? opts.threshold : 100;
    const eps = (opts && opts.eps) != null ? opts.eps : 25;
    const cool = (opts && opts.coolDownTicks) || 3;
    const out = [];
    let inEvent = null;
    let coolCount = 0;
    for (const p of clean(series)) {
      const b = bps(p.price, peg);
      const ab = Math.abs(b);
      if (!inEvent) {
        if (ab >= threshold) {
          inEvent = { firstT: p.t, lastT: p.t, peakBps: b, peakPrice: p.price };
          coolCount = 0;
        }
      } else {
        inEvent.lastT = p.t;
        if (ab > Math.abs(inEvent.peakBps)) {
          inEvent.peakBps = b;
          inEvent.peakPrice = p.price;
        }
        if (ab < eps) {
          coolCount++;
          if (coolCount >= cool) {
            const durationMs = inEvent.lastT - inEvent.firstT;
            out.push({ ...inEvent, durationMs, recoveryMs: durationMs });
            inEvent = null;
            coolCount = 0;
          }
        } else {
          coolCount = 0;
        }
      }
    }
    if (inEvent) {
      const durationMs = inEvent.lastT - inEvent.firstT;
      out.push({ ...inEvent, durationMs, recoveryMs: null }); // ongoing
    }
    return out;
  }

  // ---------------------------------------------------------------- divergence
  // Cross-source divergence at each tick: max-min bps across the available
  // sources. Spikes signal that one venue is mispricing relative to others —
  // a precursor to depeg or a routing/arbitrage opportunity.
  // Input: { binance: [{t, price}], coinbase: [...], coingecko: [...] }
  function sourceDivergence(perSourceSeries, opts) {
    const peg = (opts && opts.peg) != null ? opts.peg : 1.0;
    const sources = Object.keys(perSourceSeries);
    // Align by t: walk in lockstep using a per-source index pointer.
    const ptrs = Object.fromEntries(sources.map(s => [s, 0]));
    const lengths = Object.fromEntries(sources.map(s => [s, perSourceSeries[s].length]));
    // Collect all unique timestamps from the union of series.
    const allTs = [];
    for (const s of sources) for (const p of perSourceSeries[s]) allTs.push(p.t);
    const tsSorted = Array.from(new Set(allTs)).sort((a, b) => a - b);
    const out = [];
    for (const t of tsSorted) {
      const vals = [];
      for (const s of sources) {
        // Advance pointer to the latest tick at or before t.
        while (ptrs[s] < lengths[s] - 1 && perSourceSeries[s][ptrs[s] + 1].t <= t) ptrs[s]++;
        const last = perSourceSeries[s][ptrs[s]];
        if (last && last.t <= t && Number.isFinite(last.price)) vals.push(last.price);
      }
      if (vals.length < 2) { out.push({ t, value: NaN }); continue; }
      const mn = Math.min(...vals), mx = Math.max(...vals);
      out.push({ t, value: ((mx - mn) / peg) * 10000 });
    }
    return out;
  }

  // ----------------------------------------------------------------- expose
  window.depegIndicators = {
    // primitives
    bps, asBps, clean,
    // overlays returning [{t, value}]
    ewma, rolling, zscore, volatility, drawdown, sourceDivergence,
    // structured returns
    bollinger, recoveryTime,
  };

  // Registry consumed by the dashboard's indicator checkboxes. Each entry:
  //  - name: display label
  //  - key:  identifier
  //  - fn:   takes {series, peg, perSource} → [{t, value}] in bps-domain
  //  - color: stroke
  //  - style: 'solid' | 'dashed'
  window.depegIndicatorRegistry = [
    {
      key: 'ewma_alpha_0_3',
      name: 'ewma (α=0.3)',
      color: '#a9b0c0',
      style: 'solid',
      fn: ({ series, peg }) => asBps(ewma(series, { alpha: 0.3 }), peg),
    },
    {
      key: 'bollinger_upper',
      name: 'bollinger upper (20, k=2)',
      color: '#b58fd6',
      style: 'dashed',
      fn: ({ series, peg }) => bollinger(series, { peg, win: 20, k: 2 }).upper,
    },
    {
      key: 'bollinger_lower',
      name: 'bollinger lower (20, k=2)',
      color: '#b58fd6',
      style: 'dashed',
      fn: ({ series, peg }) => bollinger(series, { peg, win: 20, k: 2 }).lower,
    },
    {
      key: 'volatility_20',
      name: 'volatility (20-tick stddev, bps)',
      color: '#cda674',
      style: 'solid',
      fn: ({ series }) => volatility(series, { win: 20 }),
    },
    {
      key: 'drawdown',
      name: 'drawdown from peg',
      color: '#d77a7a',
      style: 'solid',
      fn: ({ series, peg }) => drawdown(series, { peg, eps: 5 }),
    },
    {
      key: 'divergence',
      name: 'cross-source divergence',
      color: '#7ec4b6',
      style: 'solid',
      fn: ({ peg, perSource }) => sourceDivergence(perSource || {}, { peg }),
    },
  ];
})();
