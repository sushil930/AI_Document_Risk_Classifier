import type { Analysis, ClassificationResult, Document, Priority } from './types';

const DATABASE_NAME = 'docuguard-browser-data';
const STORE_NAME = 'history';
const DATABASE_VERSION = 1;

export interface LocalHistoryRecord {
  id: string;
  document: Document;
  analysis: Analysis;
  file: Blob;
  extracted_text: string;
}

export function fileFromLocalRecord(record: LocalHistoryRecord): File {
  return new File([record.file], record.document.original_filename, { type: record.file.type });
}

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: 'id' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('Browser storage could not be opened.'));
  });
}

async function transaction<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORE_NAME, mode);
    const request = action(tx.objectStore(STORE_NAME));
    let result: T | undefined;
    request.onsuccess = () => { result = request.result; };
    request.onerror = () => reject(request.error || new Error('Browser storage request failed.'));
    tx.onabort = () => { database.close(); reject(tx.error || new Error('Browser storage transaction failed.')); };
    tx.oncomplete = () => { database.close(); resolve(result as T); };
    tx.onerror = () => { database.close(); reject(tx.error || new Error('Browser storage transaction failed.')); };
  });
}

export function saveLocalRecord(record: LocalHistoryRecord): Promise<IDBValidKey> {
  return transaction('readwrite', (store) => store.put(record));
}

export async function getLocalRecord(id: string): Promise<LocalHistoryRecord | undefined> {
  return transaction('readonly', (store) => store.get(id));
}

export async function getLocalHistory(): Promise<LocalHistoryRecord[]> {
  const records = await transaction('readonly', (store) => store.getAll());
  return records.sort((a, b) => b.analysis.created_at.localeCompare(a.analysis.created_at));
}

export async function deleteLocalDocument(documentId: string | number): Promise<void> {
  const records = await getLocalHistory();
  const database = await openDatabase();
  await new Promise<void>((resolve, reject) => {
    const tx = database.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    records.filter((record) => String(record.document.id) === String(documentId)).forEach((record) => store.delete(record.id));
    tx.oncomplete = () => { database.close(); resolve(); };
    tx.onabort = () => { database.close(); reject(tx.error || new Error('Could not delete this document from browser storage.')); };
    tx.onerror = () => { database.close(); reject(tx.error || new Error('Could not delete this document from browser storage.')); };
  });
}

export async function saveReviewDecision(
  analysisId: string | number,
  status: 'needs_review' | 'reviewed' | 'dismissed',
  finalLabel: Priority | null,
  note: string,
): Promise<void> {
  const record = await getLocalRecord(String(analysisId));
  if (!record?.analysis.classification) throw new Error('This local record has no classifier result.');
  const decision = { status, final_label: finalLabel, note, updated_at: new Date().toISOString() };
  const classification: ClassificationResult = { ...record.analysis.classification, review_decision: decision };
  const analysis = { ...record.analysis, classification };
  const document = { ...record.document, latest_analysis: analysis, latest_classification: classification };
  await saveLocalRecord({ ...record, analysis, document });
}

export async function getLocalDashboard() {
  const records = await getLocalHistory();
  const analyses = records.map((record) => record.analysis);
  const completed = analyses.filter((analysis) => analysis.status === 'complete');
  const latestByDocument = new Map<string, Analysis>();
  for (const analysis of analyses) {
    const key = String(analysis.document_id);
    if (!latestByDocument.has(key)) latestByDocument.set(key, analysis);
  }
  const classifications = [...latestByDocument.values()].map((analysis) => analysis.classification).filter(Boolean) as ClassificationResult[];
  const priorities = ['Low', 'Medium', 'High'] as const;
  const priorityDistribution = priorities.map((priority) => ({ overall_priority: priority, count: completed.filter((analysis) => analysis.overall_priority === priority).length })).filter((row) => row.count);
  const predictedDistribution = priorities.map((predicted_label) => ({ predicted_label, count: classifications.filter((value) => value.status === 'complete' && value.predicted_label === predicted_label).length })).filter((row) => row.count);
  const decisions = records.filter((record) => record.analysis.classification?.review_decision && record.analysis.classification.review_decision.status !== 'needs_review').slice(0, 5).map((record) => ({
    classification_id: String(record.analysis.id), document_name: record.document.original_filename,
    predicted_label: record.analysis.classification?.predicted_label || null,
    status: record.analysis.classification!.review_decision!.status,
    final_label: record.analysis.classification!.review_decision!.final_label,
    note: record.analysis.classification!.review_decision!.note,
    updated_at: record.analysis.classification!.review_decision!.updated_at,
  }));
  return {
    total_documents: latestByDocument.size,
    awaiting_review: 0,
    high_priority: completed.filter((analysis) => analysis.overall_priority === 'High').length,
    manual_review_backlog: classifications.filter((value) => value.review_required && (!value.review_decision || value.review_decision.status === 'needs_review')).length,
    reviewed_count: classifications.filter((value) => value.review_decision?.status === 'reviewed').length,
    dismissed_count: classifications.filter((value) => value.review_decision?.status === 'dismissed').length,
    priority_distribution: priorityDistribution,
    predicted_distribution: predictedDistribution,
    recent_review_decisions: decisions,
    recent_analyses: analyses.slice(0, 5),
    recent_activity: [...latestByDocument.values()].slice(0, 8).map((analysis) => records.find((record) => record.analysis.id === analysis.id)!.document),
  };
}

export function browserPreference(key: string, fallback = ''): string {
  try { return localStorage.getItem(`docuguard:${key}`) || fallback; } catch { return fallback; }
}

export function setBrowserPreference(key: string, value: string): void {
  try { localStorage.setItem(`docuguard:${key}`, value); } catch { /* Preferences are optional if browser storage is disabled. */ }
}
