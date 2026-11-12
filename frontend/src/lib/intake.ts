import type { Question } from '../api/types';

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
