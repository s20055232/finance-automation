<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, type ReportFile } from '../api/client'

const reports = ref<ReportFile[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    reports.value = await api.listReports()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})

const fmt = (bytes: number) => (bytes / 1024).toFixed(1) + ' KB'
const fmtDate = (ts: number) => new Date(ts * 1000).toLocaleString()
</script>

<template>
  <div class="reports">
    <div class="page-title">
      <h1>Reports</h1>
      <p class="subtitle">Generated Excel reconciliation reports</p>
    </div>

    <div v-if="loading" class="empty">Loading…</div>
    <div v-else-if="error" class="empty error">{{ error }}</div>

    <div v-else-if="reports.length === 0" class="empty">
      No reports yet — run a sync or upload an invoice from the Dashboard.
    </div>

    <div v-else class="report-list">
      <div v-for="r in reports" :key="r.filename" class="report-row">
        <div class="report-icon">📊</div>
        <div class="report-info">
          <div class="report-name">{{ r.filename }}</div>
          <div class="report-meta">{{ fmtDate(r.modified) }} · {{ fmt(r.size_bytes) }}</div>
        </div>
        <a :href="api.reportUrl(r.filename)" download class="btn-download">Download</a>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reports { display: flex; flex-direction: column; gap: 1.5rem; }
.page-title h1 { font-size: 1.5rem; font-weight: 700; color: #1e293b; margin: 0; }
.subtitle { color: #64748b; font-size: 0.875rem; margin: 0.25rem 0 0; }

.empty { color: #94a3b8; font-size: 0.875rem; padding: 3rem; text-align: center; }
.empty.error { color: #dc2626; }

.report-list { display: flex; flex-direction: column; gap: 0.5rem; }
.report-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.875rem 1rem;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}
.report-icon { font-size: 1.5rem; }
.report-info { flex: 1; }
.report-name { font-size: 0.875rem; font-weight: 600; color: #1e293b; font-family: monospace; }
.report-meta { font-size: 0.75rem; color: #94a3b8; margin-top: 0.15rem; }
.btn-download {
  padding: 0.4rem 0.875rem;
  border-radius: 7px;
  background: #3b82f6;
  color: #fff;
  font-size: 0.8rem;
  font-weight: 600;
  text-decoration: none;
  transition: background 0.15s;
}
.btn-download:hover { background: #2563eb; }
</style>
