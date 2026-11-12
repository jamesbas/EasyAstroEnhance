import { useState } from 'react';
import { assetImageUrl } from '../api/client';
import type { Asset, Interpretation, Question, QuestionOption } from '../api/types';
import { optionTestId } from '../lib/intake';
import { Modal } from './Modal';

interface IntakeDialogProps {
  asset: Asset;
  question: Question;
  onAnswer: (assetId: string, answer: Interpretation) => Promise<void>;
  onLater: () => void;
}

function answerFor(q: Question, option: QuestionOption): Interpretation {
  if (q.kind === 'hdu') return { hdu: Number(option.value) };
  if (q.kind === 'layout') return { layout: String(option.value) };
  return { state: option.value as Interpretation['state'] };
}

// The one exceptional prompt: shown only when a file really needs an answer.
export function IntakeDialog({ asset, question, onAnswer, onLater }: IntakeDialogProps) {
  const [busy, setBusy] = useState(false);

  const choose = async (option: QuestionOption) => {
    setBusy(true);
    try {
      await onAnswer(asset.id, answerFor(question, option));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={question.title} onClose={onLater} testId="intake-dialog" wide={question.kind === 'hdu'}>
      <p className="muted intake-file">
        For <strong>{asset.filename}</strong>
      </p>
      {question.help && <p>{question.help}</p>}
      {question.kind === 'state' && asset.thumb_url && (
        <figure className="intake-preview">
          <img src={assetImageUrl(asset, asset.thumb_url)} alt={`Preview of ${asset.filename}`} />
          <figcaption>{asset.baseline?.label ?? 'Preview'}</figcaption>
        </figure>
      )}
      <div className={question.kind === 'hdu' ? 'intake-options hdu' : 'intake-options'} role="group" aria-label={question.title}>
        {question.options.map((o) => {
          const cand = question.kind === 'hdu' ? asset.candidates.find((c) => c.index === Number(o.value)) : undefined;
          return (
            <button
              key={String(o.value)}
              type="button"
              className="intake-option"
              disabled={busy}
              data-testid={optionTestId(question, o.value)}
              onClick={() => void choose(o)}
            >
              {cand?.thumb_url && <img src={assetImageUrl(asset, cand.thumb_url)} alt="" className="intake-thumb" />}
              <span className="intake-option-text">
                <span className="intake-option-label">{o.label}</span>
                {cand && <span className="intake-option-help">Image {cand.index} · {cand.name} · {cand.shape.join(' × ')}</span>}
                {!cand && o.help && <span className="intake-option-help">{o.help}</span>}
              </span>
            </button>
          );
        })}
      </div>
      <div className="modal-actions">
        <button type="button" className="btn" onClick={onLater}>Decide later</button>
      </div>
    </Modal>
  );
}
