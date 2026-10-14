import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, CircleAlert } from 'lucide-react';
import { getLocalHistory, saveReviewDecision } from '../localHistory';
import type { Priority } from '../types';

const priorities: Priority[] = ['High', 'Medium', 'Low'];

export default function ReviewQueuePage() {
  const [status, setStatus] = useState('needs_review');
  const [priority, setPriority] = useState('');
  const [scoreBand, setScoreBand] = useState('');
  const [reason, setReason] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [ordering, setOrdering] = useState('-created_at');
  const [page, setPage] = useState(1);
  const query = useQuery({ queryKey: ['local-history'], queryFn: getLocalHistory });
  const allRecords = query.data || [];
  const matches = useMemo(() => allRecords.filter((record) => {
    const classification = record.analysis.classification;
    if (!classification?.review_required) return false;
    const decision = classification.review_decision;
    const reviewStatus = decision?.status || 'needs_review';
    const score = classification.predicted_label ? classification.class_scores[classification.predicted_label] : null;
    return (!status || reviewStatus === status)
      && (!priority || classification.predicted_label === priority)
      && (!reason || classification.review_reasons.some((value) => value.toLowerCase().includes(reason.toLowerCase())))
      && (!start || record.analysis.created_at.slice(0, 10) >= start)
      && (!end || record.analysis.created_at.slice(0, 10) <= end)
      && (!scoreBand || (scoreBand === 'unknown' && score === null)
        || (scoreBand === 'low' && score !== null && score < 0.5)
        || (scoreBand === 'medium' && score !== null && score >= 0.5 && score < 0.75)
        || (scoreBand === 'high' && score !== null && score >= 0.75));
  }).sort((a, b) => a.analysis.created_at.localeCompare(b.analysis.created_at) * (ordering.startsWith('-') ? -1 : 1)), [allRecords, status, priority, reason, start, end, scoreBand, ordering]);
  const pageSize = 10;
  const pages = Math.max(1, Math.ceil(matches.length / pageSize));
  const visible = matches.slice((page - 1) * pageSize, page * pageSize);
  const setFilter = (setter: (value: string) => void) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setter(event.target.value);
    setPage(1);
  };

  return <>
    <header className="page-header"><div><div className="section-kicker">HUMAN REVIEW · THIS BROWSER</div><h1>Flagged documents</h1><p>Review classifier triage cases saved in this browser. Decisions are not sent to the server.</p></div><Link to="/model-performance" className="button secondary">Model performance <ArrowRight size={15}/></Link></header>
    <section className="filter-bar review-filters">
      <select aria-label="Filter review status" value={status} onChange={setFilter(setStatus)}><option value="needs_review">Needs review</option><option value="reviewed">Reviewed</option><option value="dismissed">Dismissed</option><option value="">All statuses</option></select>
      <select aria-label="Filter predicted priority" value={priority} onChange={setFilter(setPriority)}><option value="">All predicted priorities</option>{priorities.map((value) => <option key={value}>{value}</option>)}</select>
      <select aria-label="Filter top model score" value={scoreBand} onChange={setFilter(setScoreBand)}><option value="">All score bands</option><option value="low">Below 50%</option><option value="medium">50% to 74.9%</option><option value="high">75% or higher</option><option value="unknown">Unavailable</option></select>
      <input aria-label="Filter review reason" placeholder="Search review reasons" value={reason} onChange={setFilter(setReason)}/>
      <input aria-label="From date" type="date" value={start} onChange={setFilter(setStart)}/>
      <input aria-label="To date" type="date" value={end} onChange={setFilter(setEnd)}/>
      <select aria-label="Sort review cases" value={ordering} onChange={setFilter(setOrdering)}><option value="-created_at">Newest first</option><option value="created_at">Oldest first</option></select>
    </section>
    {query.isLoading ? <div className="panel loading-panel">Loading local review cases…</div> : query.error ? <section className="panel error-panel"><CircleAlert/><div><b>Local review queue could not be loaded.</b><p>{query.error instanceof Error ? query.error.message : 'Try again.'}</p><button className="button secondary small" onClick={() => query.refetch()}>Retry</button></div></section> : visible.length ? <>
      <div className="review-list">{visible.map((record) => <ReviewCard key={record.id} record={record}/>)}</div>
      <div className="pagination"><span>{matches.length} cases in this browser</span><div><button className="button secondary small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page} of {pages}</span><button className="button secondary small" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button></div></div>
    </> : <section className="panel review-empty"><CircleAlert size={21}/><h2>{status === 'needs_review' ? 'The local queue is clear' : 'No matching review cases'}</h2><p>{status === 'needs_review' ? 'New classifier flags will appear here after document analysis.' : 'Try changing the filters.'}</p><Link className="text-link" to="/history">Browse this browser’s history <ArrowRight size={15}/></Link></section>}
  </>;
}

function ReviewCard({ record }: { record: Awaited<ReturnType<typeof getLocalHistory>>[number] }) {
  const queryClient = useQueryClient();
  const analysis = record.analysis;
  const classification = analysis.classification!;
  const decision = classification.review_decision;
  const [state, setState] = useState(decision?.status || 'needs_review');
  const [label, setLabel] = useState(decision?.final_label || '');
  const [note, setNote] = useState(decision?.note || '');
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const topScore = classification.predicted_label ? classification.class_scores[classification.predicted_label] : null;

  async function save() {
    if (state === 'reviewed' && !label) { setMessage('Choose the final review label before marking this case reviewed.'); return; }
    setSaving(true); setMessage('');
    try {
      await saveReviewDecision(analysis.id, state as 'needs_review' | 'reviewed' | 'dismissed', state === 'reviewed' ? label as Priority : null, note);
      await Promise.all([queryClient.invalidateQueries({ queryKey: ['local-history'] }), queryClient.invalidateQueries({ queryKey: ['dashboard'] })]);
      setMessage('Review decision saved in this browser.');
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not save this local decision.'); }
    finally { setSaving(false); }
  }

  return <article className="panel review-card">
    <div className="review-card-header"><div><span className={`priority-tag ${(classification.predicted_label || 'unrated').toLowerCase()}`}>{classification.predicted_label || 'Unrated'} prediction</span><h2>{record.document.original_filename}</h2><p>{record.document.file_type.toUpperCase()} · flagged {new Date(analysis.created_at).toLocaleString()}</p></div><span className={`review-state ${state}`}>{state.replace('_', ' ')}</span></div>
    <p className="review-summary">{analysis.summary || 'Analysis summary is not available.'}</p>
    <div className="review-score-row">{Object.entries(classification.class_scores || {}).map(([key, value]) => <span key={key}>{key}: {(value * 100).toFixed(1)}%</span>)}<small>{topScore === null ? 'Model score unavailable' : `Top model score ${(topScore * 100).toFixed(1)}%`}; this is not probability of harm.</small><small>Classifier {classification.classifier_version || 'unavailable'}</small></div>
    <div className="review-reasons"><b>Why this was flagged</b><ul>{classification.review_reasons.map((reasonText, index) => <li key={`${index}-${reasonText}`}>{reasonText}</li>)}</ul></div>
    <div className="review-card-actions"><Link className="text-link" to={`/analysis/${analysis.id}`}>Open full analysis <ArrowRight size={14}/></Link></div>
    <div className="review-form">
      <label>Review status<select value={state} onChange={(event) => setState(event.target.value as typeof state)}><option value="needs_review">Needs review</option><option value="reviewed">Reviewed</option><option value="dismissed">Dismissed</option></select></label>
      {state === 'reviewed' && <label>Final human-assessed priority<select aria-label="Final human-assessed priority" value={label} onChange={(event) => setLabel(event.target.value as Priority | '')}><option value="">Choose a priority</option>{priorities.map((value) => <option key={value}>{value}</option>)}</select></label>}
      <label className="review-note-field">Reviewer note<textarea maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional local reviewer note"/></label>
      <button className="button primary small" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save decision'}</button>
      {message && <span className="review-save-message" role="status">{message}</span>}
    </div>
  </article>;
}
