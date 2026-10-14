import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, CircleAlert } from 'lucide-react';
import { request } from '../api';
import type { Page, Priority, ReviewItem } from '../types';

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
  const params = new URLSearchParams({ status, priority, score_band: scoreBand, reason, start, end, ordering, page: String(page) });
  const query = useQuery({
    queryKey: ['reviews', status, priority, scoreBand, reason, start, end, ordering, page],
    queryFn: () => request<Page<ReviewItem>>(`/reviews/?${params}`),
  });
  const setFilter = (setter: (value: string) => void) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setter(event.target.value);
    setPage(1);
  };

  return <>
    <header className="page-header"><div><div className="section-kicker">HUMAN REVIEW</div><h1>Flagged documents</h1><p>Review classifier triage cases. Your decision is stored separately from the original prediction.</p></div><Link to="/model-performance" className="button secondary">Model performance <ArrowRight size={15}/></Link></header>
    <section className="filter-bar review-filters">
      <select aria-label="Filter review status" value={status} onChange={setFilter(setStatus)}><option value="needs_review">Needs review</option><option value="reviewed">Reviewed</option><option value="dismissed">Dismissed</option><option value="">All statuses</option></select>
      <select aria-label="Filter predicted priority" value={priority} onChange={setFilter(setPriority)}><option value="">All predicted priorities</option>{priorities.map((value) => <option key={value}>{value}</option>)}</select>
      <select aria-label="Filter top model score" value={scoreBand} onChange={setFilter(setScoreBand)}><option value="">All score bands</option><option value="low">Below 50%</option><option value="medium">50% to 74.9%</option><option value="high">75% or higher</option><option value="unknown">Unavailable</option></select>
      <input aria-label="Filter review reason" placeholder="Search review reasons" value={reason} onChange={setFilter(setReason)}/>
      <input aria-label="From date" type="date" value={start} onChange={setFilter(setStart)}/>
      <input aria-label="To date" type="date" value={end} onChange={setFilter(setEnd)}/>
      <select aria-label="Sort review cases" value={ordering} onChange={setFilter(setOrdering)}><option value="-created_at">Newest first</option><option value="created_at">Oldest first</option><option value="-predicted_label">Priority</option></select>
    </section>
    {query.isLoading ? <div className="panel loading-panel">Loading review cases…</div> : query.error ? <section className="panel error-panel"><CircleAlert/><div><b>Review queue could not be loaded.</b><p>{query.error instanceof Error ? query.error.message : 'Try again.'}</p><button className="button secondary small" onClick={() => query.refetch()}>Retry</button></div></section> : query.data?.results.length ? <>
      <div className="review-list">{query.data.results.map((item) => <ReviewCard key={item.id} item={item}/>)}</div>
      <div className="pagination"><span>{query.data.count} {query.data.count === 1 ? 'case' : 'cases'}</span><div><button className="button secondary small" disabled={!query.data.previous} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page}</span><button className="button secondary small" disabled={!query.data.next} onClick={() => setPage(page + 1)}>Next</button></div></div>
    </> : <section className="panel review-empty"><CircleAlert size={21}/><h2>{status === 'needs_review' ? 'The queue is clear' : 'No matching review cases'}</h2><p>{status === 'needs_review' ? 'New classifier flags will appear here after document analysis.' : 'Try changing the status or filters.'}</p><Link className="text-link" to="/history">Browse document history <ArrowRight size={15}/></Link></section>}
  </>;
}

function ReviewCard({ item }: { item: ReviewItem }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState(item.review_status);
  const [label, setLabel] = useState(item.final_label || '');
  const [note, setNote] = useState(item.review_note || '');
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);
  async function save() {
    if (state === 'reviewed' && !label) { setMessage('Choose the final review label before marking this case reviewed.'); return; }
    setSaving(true); setMessage('');
    try {
      await request<ReviewItem>(`/reviews/${item.id}/decision/`, { method: 'POST', body: JSON.stringify({ status: state, final_label: state === 'reviewed' ? label : null, note }) });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['reviews'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['analysis'] }),
      ]);
      setMessage('Review decision saved.');
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not save this decision.'); }
    finally { setSaving(false); }
  }

  return <article className="panel review-card">
    <div className="review-card-header"><div><span className={`priority-tag ${(item.predicted_label || 'unrated').toLowerCase()}`}>{item.predicted_label || 'Unrated'} prediction</span><h2>{item.document_name}</h2><p>{item.file_type.toUpperCase()} · flagged {new Date(item.created_at).toLocaleString()}</p></div><span className={`review-state ${item.review_status}`}>{item.review_status.replace('_', ' ')}</span></div>
    <p className="review-summary">{item.analysis_summary || 'Analysis summary is not available.'}</p>
    <div className="review-score-row">{Object.entries(item.class_scores || {}).map(([key, value]) => <span key={key}>{key}: {(value * 100).toFixed(1)}%</span>)}<small>Top score is a model triage signal, not probability of harm.</small><small>Classifier {item.classifier_version || 'unavailable'}</small></div>
    <div className="review-reasons"><b>Why this was flagged</b><ul>{item.review_reasons.map((reasonText, index) => <li key={`${index}-${reasonText}`}>{reasonText}</li>)}</ul></div>
    <div className="review-card-actions"><Link className="text-link" to={item.analysis_id ? `/analysis/${item.analysis_id}` : '/history'}>Open full analysis <ArrowRight size={14}/></Link></div>
    <div className="review-form">
      <label>Review status<select value={state} onChange={(event) => setState(event.target.value as typeof state)}><option value="needs_review">Needs review</option><option value="reviewed">Reviewed</option><option value="dismissed">Dismissed</option></select></label>
      {state === 'reviewed' && <label>Final human-assessed priority<select aria-label="Final human-assessed priority" value={label} onChange={(event) => setLabel(event.target.value as Priority | '')}><option value="">Choose a priority</option>{priorities.map((value) => <option key={value}>{value}</option>)}</select></label>}
      <label className="review-note-field">Reviewer note<textarea maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional context for this shared workspace"/></label>
      <button className="button primary small" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save decision'}</button>
      {message && <span className="review-save-message" role="status">{message}</span>}
    </div>
  </article>;
}
