import { request } from './api';
import { saveLocalRecord, type LocalHistoryRecord } from './localHistory';
import type { Analysis, ClassificationResult, Document } from './types';

interface StatelessAnalysisResponse {
  document_name: string;
  document_type: string;
  detected_document_type: string;
  file_size: number;
  extracted_text: string;
  analysis: Omit<Analysis, 'id' | 'document_id' | 'document_name' | 'document_type' | 'detected_document_type'> & {
    classification: ClassificationResult;
  };
}

function newId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export async function analyzeIntoBrowserHistory(file: File, includeAI: boolean, model: string, existingDocumentId?: string | number): Promise<LocalHistoryRecord> {
  const body = new FormData();
  body.append('file', file);
  body.append('include_ai', String(includeAI));
  if (includeAI && model) body.append('model', model);
  const result = await request<StatelessAnalysisResponse>('/documents/analyze-local/', { method: 'POST', body });
  const now = result.analysis.created_at || new Date().toISOString();
  const documentId = existingDocumentId === undefined ? newId() : String(existingDocumentId);
  const analysisId = newId();
  const analysis: Analysis = {
    ...result.analysis,
    id: analysisId,
    document_id: documentId,
    document_name: result.document_name,
    document_type: result.document_type,
    detected_document_type: result.detected_document_type,
    classification: result.analysis.classification,
  };
  const document: Document = {
    id: documentId,
    original_filename: result.document_name,
    file_type: result.document_type,
    file_size: result.file_size,
    uploaded_at: now,
    status: analysis.status,
    document_type: result.detected_document_type,
    latest_analysis: analysis,
    latest_classification: analysis.classification,
  };
  const record: LocalHistoryRecord = { id: analysisId, document, analysis, file, extracted_text: result.extracted_text };
  await saveLocalRecord(record);
  return record;
}

export async function downloadLocalPDF(analysis: Analysis): Promise<void> {
  const response = await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000/api'}/export/pdf-local/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(analysis),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.detail || `PDF export failed (HTTP ${response.status}).`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `docuguard-report-${analysis.id}.pdf`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function downloadLocalJSON(analysis: Analysis): void {
  const blob = new Blob([JSON.stringify(analysis, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `docuguard-report-${analysis.id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
