import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ArrowRight, CircleCheck, CircleX } from 'lucide-react';
import { request } from '../api';
import type { ModelPerformance, Priority } from '../types';

const labels: Priority[] = ['Low', 'Medium', 'High'];
const gateLabels: Record<string, string> = {
  dual_human_reviewed_corpus: 'Corpus has independent dual human review',
  calibrated_scores_available: 'Calibrated scores are available',
  calibration_derived_thresholds_available: 'Review thresholds come from calibration data',
  minimum_test_support_met: 'Minimum test support for every class',
  macro_f1_gate_met: 'Macro F1 meets the release threshold',
  high_recall_gate_met: 'High class recall meets the release threshold',
  ece_gate_met: 'Expected calibration error meets the limit',
  brier_gate_met: 'Multiclass Brier score meets the limit',
  auto_clear_error_gate_met: 'Errors outside review queue meet the limit',
  beats_majority_baseline: 'Macro F1 improves on the majority baseline',
};

export default function ModelPerformancePage() {
  const query = useQuery({ queryKey: ['model-performance'], queryFn: () => request<ModelPerformance>('/model-performance/') });
  if (query.isLoading) return <div className="panel loading-panel">Loading sealed evaluation…</div>;
  if (query.error) return <section className="panel error-panel"><AlertTriangle/><div><b>Evaluation could not be loaded.</b><p>{query.error instanceof Error ? query.error.message : 'Try again.'}</p><button className="button secondary small" onClick={() => query.refetch()}>Retry</button></div></section>;
  const data = query.data;
  if (!data?.available || !data.test_metrics || !data.test_calibration || !data.promotion_gate) return <section className="panel review-empty"><AlertTriangle/><h2>Evaluation report unavailable</h2><p>{data?.detail || 'Configure a classifier artifact with a sealed evaluation report.'}</p><Link to="/settings" className="text-link">Check settings <ArrowRight size={15}/></Link></section>;

  const metrics = data.test_metrics;
  const calibration = data.test_calibration;
  const gate = data.promotion_gate;
  const matrix = metrics.confusion_matrix;
  return <>
    <header className="page-header"><div><div className="section-kicker">SEALED EVALUATION</div><h1>Model performance</h1><p>Metrics measured once on the held-out split. Live document predictions are not included.</p></div><Link className="button secondary" to="/reviews">Manual review queue <ArrowRight size={15}/></Link></header>
    <section className={`gate-banner ${gate.status === 'blocked' ? 'blocked' : 'eligible'}`}><span>{gate.status === 'blocked' ? <CircleX size={21}/> : <CircleCheck size={21}/>}</span><div><b>Release gate: {gate.status.replace(/_/g, ' ')}</b><p>{data.showcase_nonproduction ? 'This is a showcase candidate using owner-approved AI-assisted labels. It is not production validated.' : 'A passing gate allows human review of the candidate; it never promotes automatically.'}</p></div></section>
    <div className="performance-stats">
      <MetricCard label="Macro F1" value={metrics.macro_f1.toFixed(3)} detail="Unweighted mean of class F1 scores"/>
      <MetricCard label="Balanced accuracy" value={metrics.balanced_accuracy.toFixed(3)} detail="Mean recall across classes"/>
      <MetricCard label="Expected calibration error" value={calibration.ece.toFixed(3)} detail="Top-label confidence gap"/>
      <MetricCard label="Test documents" value={data.test_support || 0} detail={data.scores_calibrated ? 'Sigmoid calibrated scores' : 'Uncalibrated scores'}/>
    </div>
    <div className="performance-grid">
      <section className="panel performance-panel"><div className="panel-head"><div><h2>Class-wise test results</h2><p>Precision and recall include Wilson 95% intervals.</p></div></div><div className="table-wrap"><table className="performance-table"><thead><tr><th>Class</th><th>Precision</th><th>Recall</th><th>F1</th><th>Support</th></tr></thead><tbody>{labels.map((label) => {const row = metrics.per_class[label];return <tr key={label}><td><b>{label}</b></td><td>{row.precision.toFixed(3)}<small>{interval(row.precision_95_ci)}</small></td><td>{row.recall.toFixed(3)}<small>{interval(row.recall_95_ci)}</small></td><td>{row['f1-score'].toFixed(3)}</td><td>{row.support}</td></tr>;})}</tbody></table></div></section>
      <section className="panel performance-panel"><div className="panel-head"><div><h2>Confusion matrix</h2><p>Rows are actual labels; columns are predictions.</p></div></div><div className="table-wrap"><table className="performance-table confusion-table"><thead><tr><th>Actual \ Predicted</th>{labels.map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{labels.map((label, row) => <tr key={label}><th>{label}</th>{labels.map((_, col) => <td key={col}>{matrix[row]?.[col] ?? 0}</td>)}</tr>)}</tbody></table></div></section>
      <section className="panel performance-panel"><div className="panel-head"><div><h2>Reliability</h2><p>Observed accuracy compared with predicted confidence.</p></div></div><ReliabilityPlot bins={calibration.reliability_bins}/><div className="calibration-foot"><span>ECE <b>{calibration.ece.toFixed(4)}</b></span><span>Multiclass Brier <b>{calibration.multiclass_brier.toFixed(4)}</b></span></div></section>
      <section className="panel performance-panel"><div className="panel-head"><div><h2>Manual-review policy</h2><p>Applied to held-out predictions with calibration-split thresholds.</p></div></div><div className="routing-stats"><div><b>{percent(data.test_review_routing?.review_rate)}</b><span>review rate</span></div><div><b>{percent(data.test_review_routing?.auto_clear_coverage)}</b><span>auto-clear coverage</span></div><div><b>{data.test_review_routing?.errors_outside_review_queue ?? 0}</b><span>errors outside queue</span></div></div><p className="classifier-note">An error outside the queue is a wrong class prediction among examples the threshold policy would auto-clear.</p></section>
      <section className="panel performance-panel gate-check-panel"><div className="panel-head"><div><h2>Release checks</h2><p>Criteria attached to this candidate.</p></div></div><ul>{Object.entries(gate.checks).map(([key, passed]) => <li key={key} className={passed ? 'passed' : 'failed'}>{passed ? <CircleCheck size={15}/> : <CircleX size={15}/>}<span>{gateLabels[key] || key.replace(/_/g, ' ')}</span></li>)}</ul></section>
    </div>
    <section className="panel performance-meta"><div><b>Classifier</b><span>{data.model_version}</span></div><div><b>Rubric version</b><span>{data.rubric_version || 'Not recorded'}</span></div><div><b>Evaluation date</b><span>{data.evaluated_at_utc ? new Date(data.evaluated_at_utc).toLocaleString() : 'Unknown'}</span></div><div><b>Test support</b><span>{Object.entries(data.test_class_counts || {}).map(([key, count]) => `${key} ${count}`).join(' · ')}</span></div><div><b>Corpus approval</b><span>{data.corpus_approval_mode?.replace(/_/g, ' ')}</span></div></section>
    {data.limitations?.length ? <section className="panel limitations-panel performance-limitations"><h3><AlertTriangle size={17}/> Limitations</h3><ul>{data.limitations.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></section> : null}
  </>;
}

function MetricCard({ label, value, detail }: { label: string; value: number | string; detail: string }) { return <div className="stat-card"><div className="stat-top"><span>{label}</span></div><strong>{value}</strong><small>{detail}</small></div>; }
function interval(value: number[] | null) { return value ? `95% CI ${value[0].toFixed(2)}–${value[1].toFixed(2)}` : '95% CI unavailable'; }
function percent(value?: number) { return value === undefined ? '—' : `${(value * 100).toFixed(1)}%`; }
function ReliabilityPlot({ bins }: { bins: NonNullable<ModelPerformance['test_calibration']>['reliability_bins'] }) {
  const point = (value: number, axis: 'x' | 'y') => axis === 'x' ? 62 + value * 270 : 340 - value * 270;
  return <svg className="reliability-chart" viewBox="0 0 380 400" role="img" aria-label="Calibration reliability plot">
    <line x1="62" y1="340" x2="332" y2="70" stroke="#9aa3b2" strokeDasharray="6 5"/>
    <line x1="62" y1="70" x2="62" y2="340" stroke="currentColor"/><line x1="62" y1="340" x2="332" y2="340" stroke="currentColor"/>
    <text x="197" y="388" textAnchor="middle">Mean confidence</text><text x="17" y="207" transform="rotate(-90 17 207)" textAnchor="middle">Observed accuracy</text>
    {bins.filter((bin) => bin.count && bin.mean_confidence !== null && bin.accuracy !== null).map((bin) => <circle key={`${bin.lower}-${bin.upper}`} cx={point(bin.mean_confidence!, 'x')} cy={point(bin.accuracy!, 'y')} r="6" fill="#5264d6"><title>{`n=${bin.count}, confidence=${bin.mean_confidence?.toFixed(3)}, accuracy=${bin.accuracy?.toFixed(3)}`}</title></circle>)}
  </svg>;
}
