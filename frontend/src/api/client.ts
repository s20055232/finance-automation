// API client — proxied through Vite (/api/* → http://localhost:8000) in dev

export interface OdooStatus {
  connected: boolean
  url: string
  message: string
}

export interface JournalEntry {
  account_name: string
  account_type: string
  debit_amount: number
  credit_amount: number
  description: string
}

export interface Anomaly {
  severity: 'critical' | 'warning' | 'info'
  anomaly_type: string
  invoice_number: string
  vendor_name: string
  description: string
  amount: number | null
}

export interface Invoice {
  invoice_number: string
  vendor_name: string
  invoice_date: string
  total_amount: number
  currency: string
  source_file: string
  expense_category: string
  expense_subcategory: string
  classification_confidence: 'high' | 'medium' | 'low'
  classification_source: string
  journal_entries: JournalEntry[]
  anomalies: Anomaly[]
}

export interface ReconciliationResult {
  total_invoices: number
  total_debits: number
  total_credits: number
  is_balanced: boolean
  anomaly_count: number
  critical_count: number
  warning_count: number
  cache_hits: number
  ai_calls: number
  invoices: Invoice[]
  report_filename: string | null
}

export interface ReportFile {
  filename: string
  size_bytes: number
  modified: number
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  odooStatus: () => request<OdooStatus>('/api/odoo/status'),

  odooSync: () =>
    request<ReconciliationResult>('/api/odoo/sync', { method: 'POST' }),

  uploadInvoice: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ReconciliationResult>('/api/invoices/upload', {
      method: 'POST',
      body: form,
    })
  },

  listReports: () => request<ReportFile[]>('/api/reports'),

  reportUrl: (filename: string) => `/api/reports/${filename}`,

  queryInvoices: (question: string) =>
    request<{ answer: string; indexed: number }>('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    }),
}
