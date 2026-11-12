import { useEffect, useState } from 'react';
import type { Recipe, ToneRecipe } from '../api/types';
import { clamp } from '../lib/format';
import { TONE_NEUTRAL, fractionBelow, toneIsNeutral } from '../lib/recipe';
import { Histogram } from './Histogram';

type ToneKey = 'brightness_ev' | 'shadows' | 'highlights' | 'black_point';

interface SliderSpec {
  key: ToneKey;
  id: string;
  label: string;
  unit?: string;
  min: number;
  max: number;
  step: number;
  hint: string;
}

const SLIDERS: SliderSpec[] = [
  { key: 'brightness_ev', id: 'brightness', label: 'Brightness', unit: 'EV', min: -1, max: 1, step: 0.05, hint: 'Lighten (+) or darken (−) overall, in exposure steps' },
  { key: 'shadows', id: 'shadows', label: 'Shadows', min: -1, max: 1, step: 0.05, hint: 'Open up (+) or deepen (−) dark areas' },
  { key: 'highlights', id: 'highlights', label: 'Highlights', min: -1, max: 1, step: 0.05, hint: 'Brighten (+) or recover (−) bright areas' },
  { key: 'black_point', id: 'black-point', label: 'Black point', min: -0.05, max: 0.1, step: 0.005, hint: 'Raise to darken the sky; very small steps' },
];

function decimals(step: number): number {
  return step < 0.01 ? 3 : 2;
}

function NumberField({ value, min, max, step, label, onCommit }: { value: number; min: number; max: number; step: number; label: string; onCommit: (v: number) => void }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => setText(null), [value]);
  const commit = (raw: string) => {
    const n = Number(raw);
    if (raw.trim() !== '' && Number.isFinite(n)) onCommit(clamp(Math.round(n / step) * step, min, max));
    setText(null);
  };
  return (
    <input
      type="number"
      className="num"
      aria-label={`${label} value`}
      min={min}
      max={max}
      step={step}
      value={text ?? value.toFixed(decimals(step))}
      onChange={(e) => setText(e.target.value)}
      onBlur={(e) => commit(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit((e.target as HTMLInputElement).value);
      }}
    />
  );
}

interface ToneControlsProps {
  tone: ToneRecipe;
  histogram: number[] | null;
  edit: (mutate: (r: Recipe) => void) => void;
}

export function ToneControls({ tone, histogram, edit }: ToneControlsProps) {
  const set = (key: ToneKey, v: number) => edit((r) => { r.tone[key] = Number(v.toFixed(3)); });
  const clip = histogram && tone.black_point > 0 ? fractionBelow(histogram, tone.black_point) : null;

  return (
    <details className="disclosure" data-testid="tone-disclosure">
      <summary>Tone controls</summary>
      <div className="disclosure-body">
        <p className="muted small">Small manual offsets on top of the chosen preset. They start at zero.</p>
        {SLIDERS.map((s) => {
          const value = tone[s.key];
          const zeroPct = ((0 - s.min) / (s.max - s.min)) * 100;
          return (
            <div className="slider-row" key={s.key}>
              <div className="slider-head">
                <label htmlFor={`tone-${s.id}`}>{s.label}{s.unit ? ` (${s.unit})` : ''}</label>
                <NumberField value={value} min={s.min} max={s.max} step={s.step} label={s.label} onCommit={(v) => set(s.key, v)} />
                <button type="button" className="btn tiny" disabled={value === 0} onClick={() => set(s.key, 0)} aria-label={`Reset ${s.label}`}>Reset</button>
              </div>
              <div className="range-wrap">
                <input
                  id={`tone-${s.id}`}
                  type="range"
                  min={s.min}
                  max={s.max}
                  step={s.step}
                  value={value}
                  data-testid={`slider-${s.id}`}
                  aria-describedby={`tone-${s.id}-hint`}
                  onChange={(e) => set(s.key, Number(e.target.value))}
                />
                <span className="zero-tick" style={{ left: `calc(${zeroPct}% + ${(0.5 - zeroPct / 100) * 16}px)` }} aria-hidden="true" title="Zero (default)" />
              </div>
              <p className="slider-hint" id={`tone-${s.id}-hint`}>{s.hint}</p>
              {s.key === 'black_point' && value !== 0 && <Histogram histogram={histogram} blackPoint={value} clipFraction={clip} />}
            </div>
          );
        })}
        <button type="button" className="btn small" data-testid="reset-tone" disabled={toneIsNeutral(tone)} onClick={() => edit((r) => Object.assign(r.tone, TONE_NEUTRAL))}>
          Reset tone
        </button>
      </div>
    </details>
  );
}
