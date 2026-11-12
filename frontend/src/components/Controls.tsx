import { STRENGTHS, STRENGTH_LABEL } from '../lib/recipe';
import type { Strength } from '../api/types';

interface SegmentedProps {
  value: Strength;
  onChange: (s: Strength) => void;
  label: string;
  disabled?: boolean;
  testId?: string;
}

export function StrengthButtons({ value, onChange, label, disabled, testId }: SegmentedProps) {
  return (
    <div className="segmented small" role="group" aria-label={`${label} strength`} data-testid={testId}>
      {STRENGTHS.map((s) => (
        <button
          key={s}
          type="button"
          className={value === s ? 'seg active' : 'seg'}
          aria-pressed={value === s}
          disabled={disabled}
          onClick={() => onChange(s)}
        >
          {STRENGTH_LABEL[s]}
        </button>
      ))}
    </div>
  );
}

interface SwitchProps {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
  testId?: string;
  describedBy?: string;
}

export function Switch({ checked, onChange, label, disabled, testId, describedBy }: SwitchProps) {
  return (
    <label className={`switch${disabled ? ' disabled' : ''}`}>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        data-testid={testId}
        aria-describedby={describedBy}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="switch-track" aria-hidden="true"><span className="switch-thumb" /></span>
      <span className="switch-label">{label}</span>
    </label>
  );
}
