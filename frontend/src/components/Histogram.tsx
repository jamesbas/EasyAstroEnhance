interface HistogramProps {
  histogram: number[] | null;
  blackPoint: number;
  clipFraction: number | null;
  testId?: string;
}

const W = 256;
const H = 56;

// 256-bin luminance histogram (square-root scaled so faint-sky peaks do not flatten the rest).
export function Histogram({ histogram, blackPoint, clipFraction, testId = 'histogram' }: HistogramProps) {
  if (!histogram || histogram.length === 0) {
    return <p className="muted small">The histogram appears once the preview is ready.</p>;
  }
  const bins = histogram.length;
  const max = Math.max(...histogram.map((v) => Math.sqrt(v)), 1);
  const bw = W / bins;
  const markerX = Math.min(Math.max(blackPoint, 0), 1) * W;
  return (
    <figure className="histogram" data-testid={testId}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Luminance histogram of the original view">
        {histogram.map((v, i) => {
          const h = (Math.sqrt(v) / max) * (H - 2);
          return <rect key={i} x={i * bw} y={H - h} width={bw + 0.2} height={h} className="hist-bar" />;
        })}
        {blackPoint !== 0 && (
          <>
            {blackPoint > 0 && <rect x={0} y={0} width={markerX} height={H} className="hist-clip" />}
            <line x1={markerX} x2={markerX} y1={0} y2={H} className="hist-marker" data-testid="histogram-marker" />
          </>
        )}
      </svg>
      {blackPoint > 0 && clipFraction !== null && (
        <figcaption data-testid="clip-estimate">
          Black point {blackPoint.toFixed(3)} will clip ~{(clipFraction * 100).toFixed(clipFraction < 0.1 ? 1 : 0)}% of pixels
          <span className="muted"> (estimated from the original view)</span>
        </figcaption>
      )}
      {blackPoint < 0 && <figcaption>A negative black point lifts the darkest tones; nothing is clipped.</figcaption>}
    </figure>
  );
}
