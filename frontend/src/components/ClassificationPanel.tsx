import { CircleAlert, ShieldCheck } from 'lucide-react';
import type { ClassificationResult } from '../types';

export default function ClassificationPanel({ result }: { result?: ClassificationResult | null }) {
  if (!result) return null;

  const title = result.status === 'unable_to_assess'
    ? 'Unable to assess'
    : result.status === 'unavailable'
      ? 'Classifier unavailable'
      : `${result.predicted_label ?? 'Unclassified'} classifier result`;

  return (
    <section className="panel classifier-panel" aria-labelledby="classifier-heading">
      <div className="classifier-heading">
        <div>
          <span className="section-kicker">DOCUMENT TRIAGE</span>
          <h2 id="classifier-heading">{title}</h2>
        </div>
        {result.review_required
          ? <span className="badge medium"><CircleAlert size={14}/> Manual review required</span>
          : <span className="badge low"><ShieldCheck size={14}/> No review flag</span>}
      </div>

      {result.status === 'complete' && (
        <>
          <div className="classifier-scores">
            {Object.entries(result.class_scores).map(([label, score]) => (
              <div className="classifier-score" key={label}>
                <div><span>{label}</span><b>{(score * 100).toFixed(1)}%</b></div>
                <progress max={1} value={score} aria-label={`${label} model score`}/>
              </div>
            ))}
          </div>
          <p className="classifier-note">Model class scores are triage signals, not probabilities of harm or compliance.</p>
          <div className="classifier-explanations">
            <div>
              <h3>Classifier feature signals</h3>
              <p className="classifier-note">Terms that influenced this model output. These are not document evidence.</p>
              <div className="signal-columns">
                <div><b>Supported this class</b>{result.feature_signals?.supporting?.length ? <ul>{result.feature_signals.supporting.map((item, index) => <li key={`${item.term}-${index}`}>{item.term}</li>)}</ul> : <p className="classifier-note">No terms available.</p>}</div>
                <div><b>Counted against this class</b>{result.feature_signals?.opposing?.length ? <ul>{result.feature_signals.opposing.map((item, index) => <li key={`${item.term}-${index}`}>{item.term}</li>)}</ul> : <p className="classifier-note">No terms available.</p>}</div>
              </div>
            </div>
            <div>
              <h3>Similar training examples</h3>
              <p className="classifier-note">Sanitized references from the training split; source document text is not shown.</p>
              {result.nearest_examples?.length ? <ul className="nearest-examples">{result.nearest_examples.map((item) => <li key={item.sample_id}><span>{item.label} · {item.source_type}</span><small>{item.sample_id} · similarity {(item.similarity * 100).toFixed(1)}%</small></li>)}</ul> : <p className="classifier-note">No reference examples available.</p>}
            </div>
          </div>
        </>
      )}

      {result.review_required && result.review_reasons.length > 0 && (
        <ul className="classifier-reasons">
          {result.review_reasons.map((reason, index) => <li key={`${index}-${reason}`}>{reason}</li>)}
        </ul>
      )}
      {result.classifier_version && <small className="classifier-version">Classifier: {result.classifier_version}</small>}
    </section>
  );
}
