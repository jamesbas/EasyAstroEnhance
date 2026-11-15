import type { LookRecipe, Recipe } from '../api/types';
import { LOOK_SLIDERS } from '../lib/recipe';
import { Switch } from './Controls';

interface LookControlsProps {
  look: LookRecipe;
  stretchOn: boolean;
  mono: boolean;
  edit: (mutate: (r: Recipe) => void) => void;
}

function format(value: number, step: number, signed: boolean): string {
  const digits = step < 0.1 ? 2 : 1;
  const text = value.toFixed(digits);
  return signed && value > 0 ? `+${text}` : text;
}

// The six main sliders and the bright-core switch. The preset sets them; Enhance measures everything else.
export function LookControls({ look, stretchOn, mono, edit }: LookControlsProps) {
  return (
    <section className="look" aria-label="Look" data-testid="look-controls">
      <h3 className="section-title">Look</h3>
      {LOOK_SLIDERS.map((s) => {
        const value = look[s.key];
        const disabled = (s.colorOnly && mono) || (s.key === 'stretch' && !stretchOn);
        const hint = s.colorOnly && mono ? 'Not available for monochrome images.' : s.key === 'stretch' && !stretchOn ? 'The stretch is switched off in Advanced.' : s.hint;
        return (
          <div className="slider-row" key={s.key}>
            <div className="slider-head">
              <label htmlFor={`look-${s.id}`}>{s.label}</label>
              <output className="slider-value" htmlFor={`look-${s.id}`} data-testid={`value-${s.id}`}>{format(value, s.step, s.min < 0)}</output>
            </div>
            <div className="range-wrap">
              <input
                id={`look-${s.id}`}
                type="range"
                min={s.min}
                max={s.max}
                step={s.step}
                value={value}
                disabled={disabled}
                data-testid={`slider-${s.id}`}
                aria-describedby={`look-${s.id}-hint`}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  edit((r) => { r.look[s.key] = Number(v.toFixed(3)); });
                }}
              />
            </div>
            <div className="range-ends" aria-hidden="true"><span>{s.left}</span><span>{s.right}</span></div>
            <p className="slider-hint" id={`look-${s.id}-hint`}>{hint}</p>
          </div>
        );
      })}
      <div className="option-row on">
        <Switch
          checked={look.protect_cores}
          onChange={(v) => edit((r) => { r.look.protect_cores = v; })}
          label="Protect bright cores"
          testId="switch-protect-cores"
          describedBy="hint-protect-cores"
        />
        <p className="option-hint" id="hint-protect-cores">Keeps galaxy and nebula cores (M42, M31) from blowing out; compressed only when a bright extended core is found.</p>
      </div>
    </section>
  );
}
