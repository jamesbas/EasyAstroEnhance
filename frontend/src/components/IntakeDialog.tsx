import { useState } from 'react';
import { assetImageUrl } from '../api/client';
import type { Asset, Interpretation, Question, QuestionOption } from '../api/types';
import { answerFor, optionTestId } from '../lib/intake';
import { Modal } from './Modal';

interface IntakeDialogProps {
  asset: Asset;
  question: Question;
  onAnswer: (assetId: string, answer: Interpretation) => Promise<void>;
  onLater: () => void;
  /** answer every open question of every file that has recommendations for all of them (this file included) */
  bulk?: { count: number; onApply: () => Promise<void> } | null;
}

// The one exceptional prompt: shown only when a file really needs an answer.
export function IntakeDialog({ asset, question, onAnswer, onLater, bulk }: IntakeDialogProps) {
  const [busy, setBusy] = useState(false);
  const recommended = question.recommended;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };
  const choose = (option: QuestionOption) => run(() => onAnswer(asset.id, answerFor(question, option.value)));

  return (
    <Modal title={question.title} onClose={onLater} testId="intake-dialog" wide={question.kind === 'hdu'}>
      <p className="muted intake-file">
        For <strong>{asset.filename}</strong>
      </p>
      {question.help && <p>{question.help}</p>}
      {recommended !== undefined && question.recommendation_reason && (
        <p className="intake-recommendation small" data-testid="intake-recommendation">
          <strong>Recommended:</strong> {question.recommendation_reason} Please confirm.
        </p>
      )}
      {question.kind === 'state' && asset.thumb_url && (
        <figure className="intake-preview">
          <img src={assetImageUrl(asset, asset.thumb_url)} alt={`Preview of ${asset.filename}`} />
          <figcaption>{asset.baseline?.label ?? 'Preview'}</figcaption>
        </figure>
      )}
      <div className={question.kind === 'hdu' ? 'intake-options hdu' : 'intake-options'} role="group" aria-label={question.title}>
        {question.options.map((o) => {
          const cand = question.kind === 'hdu' ? asset.candidates.find((c) => c.index === Number(o.value)) : undefined;
          const isRecommended = recommended !== undefined && String(o.value) === String(recommended);
          return (
            <button
              key={String(o.value)}
              type="button"
              className={isRecommended ? 'intake-option recommended' : 'intake-option'}
              disabled={busy}
              data-testid={optionTestId(question, o.value)}
              autoFocus={isRecommended}
              onClick={() => void choose(o)}
            >
              {cand?.thumb_url && <img src={assetImageUrl(asset, cand.thumb_url)} alt="" className="intake-thumb" />}
              <span className="intake-option-text">
                <span className="intake-option-label">
                  {o.label}
                  {isRecommended && <span className="badge ok intake-badge" data-testid="recommended-badge">Recommended</span>}
                </span>
                {cand && <span className="intake-option-help">Image {cand.index} · {cand.name} · {cand.shape.join(' × ')}</span>}
                {!cand && o.help && <span className="intake-option-help">{o.help}</span>}
              </span>
            </button>
          );
        })}
      </div>
      <div className="modal-actions">
        {bulk && (
          <button type="button" className="btn primary" disabled={busy} onClick={() => void run(bulk.onApply)} data-testid="intake-apply-recommended">
            {bulk.count > 1 ? `Use recommended answers for all ${bulk.count} files` : 'Use recommended answers'}
          </button>
        )}
        <button type="button" className="btn" onClick={onLater}>Decide later</button>
      </div>
    </Modal>
  );
}
