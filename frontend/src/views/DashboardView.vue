<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, type OdooStatus, type ReconciliationResult as ReconciliationData } from '../api/client'
import ReconciliationResult from '../components/ReconciliationResult.vue'

const odooStatus = ref<OdooStatus | null>(null)
const result = ref<ReconciliationData | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const question = ref('')
const queryAnswer = ref<string | null>(null)
const queryLoading = ref(false)
const queryError = ref<string | null>(null)

async function askQuestion() {
  if (!question.value.trim()) return
  queryLoading.value = true
  queryAnswer.value = null
  queryError.value = null
  try {
    const res = await api.queryInvoices(question.value.trim())
    queryAnswer.value = res.answer
  } catch (e) {
    queryError.value = (e as Error).message
  } finally {
    queryLoading.value = false
  }
}

onMounted(async () => {
  try {
    odooStatus.value = await api.odooStatus()
  } catch {
    // Odoo status is optional; silently ignore if backend not ready
  }
})

async function syncOdoo() {
  loading.value = true
  error.value = null
  result.value = null
  try {
    result.value = await api.odooSync()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function uploadFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  loading.value = true
  error.value = null
  result.value = null
  try {
    result.value = await api.uploadInvoice(file)
  } catch (err) {
    error.value = (err as Error).message
  } finally {
    loading.value = false
    ;(e.target as HTMLInputElement).value = ''
  }
}
</script>

<template>
  <div class="dashboard">
    <div class="page-title">
      <h1>Invoice Processing</h1>
      <p class="subtitle">AI-powered classification, journal entries, and anomaly detection</p>
    </div>

    <!-- Action cards -->
    <div class="action-row">
      <!-- Odoo Sync -->
      <div class="card">
        <div class="card-header">
          <div class="card-icon odoo-icon">🔗</div>
          <div>
            <h2 class="card-title">Sync from Odoo</h2>
            <p class="card-desc">Pull posted vendor bills and run the full pipeline</p>
          </div>
        </div>

        <div v-if="odooStatus" class="status-badge" :class="odooStatus.connected ? 'ok' : 'err'">
          <span class="dot" />
          {{ odooStatus.connected ? 'Connected' : 'Disconnected' }}
          <span class="status-msg">{{ odooStatus.message }}</span>
        </div>

        <button
          class="btn btn-primary"
          :disabled="loading || !odooStatus?.connected"
          @click="syncOdoo"
        >
          {{ loading ? 'Processing…' : 'Run Sync' }}
        </button>
      </div>

      <!-- File Upload -->
      <div class="card">
        <div class="card-header">
          <div class="card-icon upload-icon">📄</div>
          <div>
            <h2 class="card-title">Upload Invoice</h2>
            <p class="card-desc">Process a single PDF or CSV invoice file</p>
          </div>
        </div>

        <label class="upload-area" :class="{ disabled: loading }">
          <input
            type="file"
            accept=".pdf,.csv,.xlsx"
            :disabled="loading"
            @change="uploadFile"
          />
          <span class="upload-hint">Click or drag a file here</span>
          <span class="upload-formats">PDF · CSV · XLSX</span>
        </label>
      </div>
    </div>

    <!-- Error -->
    <div v-if="error" class="error-banner">
      <strong>Error:</strong> {{ error }}
    </div>

    <!-- Loading -->
    <div v-if="loading" class="loading-banner">
      <div class="spinner" />
      Running pipeline — classifying with Claude AI, generating journal entries…
    </div>

    <!-- Results -->
    <div v-if="result" class="results-section">
      <div class="results-header">
        <h2>Results</h2>
        <a
          v-if="result.report_filename"
          :href="`/api/reports/${result.report_filename}`"
          download
          class="btn btn-outline"
        >
          Download Excel Report
        </a>
      </div>
      <ReconciliationResult :result="result" />
    </div>

    <!-- Natural language query -->
    <div class="query-section">
      <h2 class="query-title">Ask about your invoices</h2>
      <p class="query-hint">Run a sync first to index invoices, then ask anything.</p>
      <div class="query-row">
        <input
          v-model="question"
          class="query-input"
          placeholder="e.g. 這個月廣告費共花了多少？"
          :disabled="queryLoading"
          @keydown.enter="askQuestion"
        />
        <button class="btn btn-primary" :disabled="queryLoading || !question.trim()" @click="askQuestion">
          {{ queryLoading ? '…' : 'Ask' }}
        </button>
      </div>
      <div v-if="queryError" class="error-banner">{{ queryError }}</div>
      <div v-if="queryAnswer" class="query-answer">{{ queryAnswer }}</div>
    </div>
  </div>
</template>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: 1.5rem; }
.page-title h1 { font-size: 1.5rem; font-weight: 700; color: #1e293b; margin: 0; }
.subtitle { color: #64748b; font-size: 0.875rem; margin: 0.25rem 0 0; }

.action-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }

.card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.card-header { display: flex; align-items: flex-start; gap: 1rem; }
.card-icon { font-size: 1.75rem; line-height: 1; }
.card-title { font-size: 1rem; font-weight: 600; color: #1e293b; margin: 0; }
.card-desc { font-size: 0.8rem; color: #64748b; margin: 0.2rem 0 0; }

.status-badge {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  font-weight: 500;
  padding: 0.4rem 0.75rem;
  border-radius: 8px;
}
.status-badge.ok { background: #f0fdf4; color: #16a34a; }
.status-badge.err { background: #fef2f2; color: #dc2626; }
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.status-msg { color: #64748b; font-weight: 400; font-size: 0.75rem; }

.btn {
  padding: 0.6rem 1.25rem;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: background 0.15s, opacity 0.15s;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: #3b82f6; color: #fff; }
.btn-primary:not(:disabled):hover { background: #2563eb; }
.btn-outline {
  background: transparent;
  border: 1px solid #cbd5e1;
  color: #475569;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}
.btn-outline:hover { background: #f8fafc; }

.upload-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.3rem;
  padding: 1.5rem;
  border: 2px dashed #cbd5e1;
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.upload-area:not(.disabled):hover { border-color: #3b82f6; background: #eff6ff; }
.upload-area.disabled { opacity: 0.5; cursor: not-allowed; }
.upload-area input { display: none; }
.upload-hint { font-size: 0.875rem; color: #475569; font-weight: 500; }
.upload-formats { font-size: 0.75rem; color: #94a3b8; }

.error-banner {
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  color: #dc2626;
  font-size: 0.875rem;
}
.loading-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  color: #1d4ed8;
  font-size: 0.875rem;
}
.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid #bfdbfe;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

.results-section { display: flex; flex-direction: column; gap: 1rem; }
.results-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.results-header h2 { font-size: 1.1rem; font-weight: 600; color: #1e293b; margin: 0; }

.query-section {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.query-title { font-size: 1rem; font-weight: 600; color: #1e293b; margin: 0; }
.query-hint  { font-size: 0.8rem; color: #94a3b8; margin: 0; }
.query-row   { display: flex; gap: 0.5rem; }
.query-input {
  flex: 1;
  padding: 0.55rem 0.875rem;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.875rem;
  outline: none;
  transition: border-color 0.15s;
}
.query-input:focus { border-color: #3b82f6; }
.query-input:disabled { opacity: 0.5; }
.query-answer {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.875rem 1rem;
  font-size: 0.875rem;
  color: #334155;
  line-height: 1.6;
  white-space: pre-wrap;
}
</style>
