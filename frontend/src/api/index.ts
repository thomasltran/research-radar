import React from 'react';
import type { SortMode, Paper } from '../types';

export const API = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '');

export const SORT_OPTIONS: Array<{ value: SortMode; label: string }> = [
  { value: 'relevance', label: 'Relevance' },
  { value: 'title', label: 'A-Z' },
  { value: 'published', label: 'Source date' },
  { value: 'new', label: 'Added date' },
  { value: 'unread', label: 'Unread first' },
];

export type FetchJsonOptions = RequestInit & {
  timeoutMs?: number;
};

export async function fetchJson<T>(path: string, init: FetchJsonOptions = {}): Promise<T> {
  const { timeoutMs = 15000, signal, ...requestInit } = init;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  if (signal) {
    signal.addEventListener('abort', () => controller.abort(), { once: true });
  }

  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      ...requestInit,
    });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error('Request timed out. The job may still be running; retry or check Reports.');
    }
    throw error instanceof Error ? error : new Error(String(error));
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export function sortPapers(papers: Paper[], mode: SortMode, semanticActive = false): Paper[] {
  const copy = [...papers];
  const dateValue = (value?: string) => value ? Date.parse(value) || 0 : 0;

  return copy.sort((a, b) => {
    if (semanticActive) return (b.semantic_score ?? -1) - (a.semantic_score ?? -1);
    if (mode === 'title') return a.title.localeCompare(b.title);
    if (mode === 'published') return dateValue(b.published_date) - dateValue(a.published_date);
    if (mode === 'new') return dateValue(b.ingested_at) - dateValue(a.ingested_at);
    if (mode === 'unread') return Number(a.read) - Number(b.read) || (b.relevance_score ?? -1) - (a.relevance_score ?? -1);
    return (b.relevance_score ?? -1) - (a.relevance_score ?? -1) || a.title.localeCompare(b.title);
  });
}
