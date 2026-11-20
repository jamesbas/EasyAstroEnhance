import type { Asset, Interpretation, Question } from '../api/types';

// Mirrors the backend's state question; used to let people revisit an "I'm not sure" answer.
export const STATE_QUESTION: Question = {
  id: 'state',
  kind: 'state',
  title: 'How was this image saved?',
  options: [
    { value: 'linear', label: 'Linear stack', help: 'Straight from stacking, before any stretch. Uses the separate linear pipeline.' },
    { value: 'rendered', label: 'Already processed', help: 'Already stretched or adjusted for viewing. Uses the display-image pipeline.' },
    { value: 'unsure', label: "I'm not sure", help: 'Shows a clearly labeled preview only. Enhancement stays blocked until you confirm.' },
  ],
};

export function optionTestId(q: Question, value: string | number): string {
  if (q.kind === 'state') return `intake-option-${value}`;
  return `intake-option-${q.kind}-${value}`;
}

export function answerFor(q: Question, value: string | number): Interpretation {
  if (q.kind === 'hdu') return { hdu: Number(value) };
  if (q.kind === 'layout') return { layout: String(value) };
  return { state: value as Interpretation['state'] };
}

/** Every open question of the asset answered with its recommendation, or null when any question has none. */
export function recommendedAnswers(asset: Asset): Interpretation | null {
  if (asset.status !== 'needs_input' || asset.questions.length === 0) return null;
  let out: Interpretation = {};
  for (const q of asset.questions) {
    if (q.recommended === undefined) return null;
    out = { ...out, ...answerFor(q, q.recommended) };
  }
  return out;
}
