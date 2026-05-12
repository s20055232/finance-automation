<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ReconciliationResult, Anomaly } from '../api/client'

const props = defineProps<{ result: ReconciliationResult }>()

const expandedInvoice = ref<string | null>(null)

function toggleInvoice(id: string) {
  expandedInvoice.value = expandedInvoice.value === id ? null : id
}

const fmt = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n)

const severityClass = (s: Anomaly['severity']) =>
  ({ critical: 'sev-critical', warning: 'sev-warning', info: 'sev-info' })[s]

const confidenceClass = (c: string) =>
  ({ high: 'conf-high', medium: 'conf-medium', low: 'conf-low' })[c] ?? ''

// ── Trial Balance：把所有分錄按帳戶彙總 ──────────────────────────────────────
interface TrialRow {
  account_name: string
  account_type: string
  total_debits: number
  total_credits: number
  net: number
}

const trialBalance = computed<TrialRow[]>(() => {
  const map = new Map<string, TrialRow>()
  for (const inv of props.result.invoices) {
    for (const e of inv.journal_entries) {
      if (!map.has(e.account_name)) {
        map.set(e.account_name, {
          account_name: e.account_name,
          account_type: e.account_type,
          total_debits: 0,
          total_credits: 0,
          net: 0,
        })
      }
      const row = map.get(e.account_name)!
      row.total_debits  += e.debit_amount
      row.total_credits += e.credit_amount
      row.net = row.total_debits - row.total_credits
    }
  }
  return [...map.values()].sort((a, b) => a.account_type.localeCompare(b.account_type))
})
</script>

<template>
  <div class="result">
    <!-- ── Summary cards ──────────────────────────────────────────────────── -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ props.result.total_invoices }}</div>
        <div class="stat-label">Invoices</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ fmt(props.result.total_debits) }}</div>
        <div class="stat-label">Total Debits</div>
      </div>
      <div class="stat-card" :class="props.result.is_balanced ? 'stat-ok' : 'stat-err'">
        <div class="stat-value">{{ props.result.is_balanced ? '✓' : '✗' }}</div>
        <div class="stat-label">{{ props.result.is_balanced ? 'Balanced' : 'Unbalanced' }}</div>
      </div>
      <div class="stat-card" :class="{ 'stat-err': props.result.critical_count > 0 }">
        <div class="stat-value">{{ props.result.anomaly_count }}</div>
        <div class="stat-label">Anomalies ({{ props.result.critical_count }} critical)</div>
      </div>
      <div class="stat-card stat-cache">
        <div class="stat-value">{{ props.result.cache_hits }}/{{ props.result.total_invoices }}</div>
        <div class="stat-label">Cached ({{ props.result.ai_calls }} AI calls)</div>
      </div>
    </div>

    <!-- ── Anomalies ──────────────────────────────────────────────────────── -->
    <div v-if="props.result.anomaly_count > 0" class="section">
      <h3 class="section-title">Anomalies</h3>
      <div class="anomaly-list">
        <div
          v-for="(anomaly, idx) in props.result.invoices.flatMap(i => i.anomalies)"
          :key="anomaly.invoice_number + anomaly.anomaly_type + idx"
          class="anomaly-row"
          :class="severityClass(anomaly.severity)"
        >
          <span class="anomaly-badge">{{ anomaly.severity.toUpperCase() }}</span>
          <span class="anomaly-inv">{{ anomaly.invoice_number }}</span>
          <span class="anomaly-desc">{{ anomaly.description }}</span>
          <span v-if="anomaly.amount" class="anomaly-amt">{{ fmt(anomaly.amount) }}</span>
        </div>
      </div>
    </div>

    <!-- ── Trial Balance ──────────────────────────────────────────────────── -->
    <div v-if="trialBalance.length > 0" class="section">
      <h3 class="section-title">Trial Balance</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Account</th>
              <th>Type</th>
              <th class="text-right">Debit</th>
              <th class="text-right">Credit</th>
              <th class="text-right">Net</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in trialBalance" :key="row.account_name">
              <td class="acct-name">{{ row.account_name }}</td>
              <td class="acct-type">{{ row.account_type }}</td>
              <td class="text-right mono">{{ row.total_debits > 0 ? fmt(row.total_debits) : '—' }}</td>
              <td class="text-right mono">{{ row.total_credits > 0 ? fmt(row.total_credits) : '—' }}</td>
              <td class="text-right mono" :class="row.net < 0 ? 'neg' : ''">
                {{ fmt(Math.abs(row.net)) }}{{ row.net < 0 ? ' Cr' : row.net > 0 ? ' Dr' : '' }}
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr class="total-row">
              <td colspan="2">Total</td>
              <td class="text-right mono">{{ fmt(props.result.total_debits) }}</td>
              <td class="text-right mono">{{ fmt(props.result.total_credits) }}</td>
              <td class="text-right">
                <span :class="props.result.is_balanced ? 'badge-ok' : 'badge-err'">
                  {{ props.result.is_balanced ? 'Balanced' : 'Off' }}
                </span>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>

    <!-- ── Invoices table（展開看分錄）────────────────────────────────────── -->
    <div class="section">
      <h3 class="section-title">Invoices</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th style="width:1.5rem"></th>
              <th>Invoice #</th>
              <th>Vendor</th>
              <th>Date</th>
              <th>Category</th>
              <th>Confidence</th>
              <th>Source</th>
              <th class="text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="inv in props.result.invoices" :key="inv.invoice_number">
              <!-- Main row -->
              <tr
                class="inv-row"
                :class="{ 'row-anomaly': inv.anomalies.length > 0, 'row-expanded': expandedInvoice === inv.invoice_number }"
                @click="toggleInvoice(inv.invoice_number)"
              >
                <td class="chevron">{{ expandedInvoice === inv.invoice_number ? '▾' : '▸' }}</td>
                <td class="mono">{{ inv.invoice_number }}</td>
                <td>{{ inv.vendor_name }}</td>
                <td class="mono">{{ inv.invoice_date }}</td>
                <td>{{ inv.expense_category }}</td>
                <td>
                  <span class="conf-badge" :class="confidenceClass(inv.classification_confidence)">
                    {{ inv.classification_confidence }}
                  </span>
                </td>
                <td class="source">{{ inv.source_file.startsWith('odoo:') ? 'Odoo' : 'PDF/CSV' }}</td>
                <td class="text-right mono">{{ fmt(inv.total_amount) }}</td>
              </tr>

              <!-- Journal entries expand row -->
              <tr v-if="expandedInvoice === inv.invoice_number" class="entries-row">
                <td colspan="8" class="entries-cell">
                  <div class="entries-wrap">
                    <div class="entries-header">Journal Entries</div>
                    <table class="entries-table">
                      <thead>
                        <tr>
                          <th>Account</th>
                          <th>Type</th>
                          <th>Description</th>
                          <th class="text-right">Debit</th>
                          <th class="text-right">Credit</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="(e, i) in inv.journal_entries" :key="i">
                          <td class="e-account">{{ e.account_name }}</td>
                          <td class="e-type">{{ e.account_type }}</td>
                          <td class="e-desc">{{ e.description }}</td>
                          <td class="text-right mono e-amt">
                            {{ e.debit_amount > 0 ? fmt(e.debit_amount) : '' }}
                          </td>
                          <td class="text-right mono e-amt">
                            {{ e.credit_amount > 0 ? fmt(e.credit_amount) : '' }}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                    <div v-if="inv.anomalies.length > 0" class="entry-anomalies">
                      <span v-for="a in inv.anomalies" :key="a.anomaly_type"
                            class="anomaly-tag" :class="severityClass(a.severity)">
                        {{ a.severity.toUpperCase() }}: {{ a.description }}
                      </span>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.result { display: flex; flex-direction: column; gap: 1.5rem; }

/* ── Stats ── */
.stats-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 1rem; }
.stat-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 1rem 1.25rem;
  text-align: center;
}
.stat-value { font-size: 1.5rem; font-weight: 700; color: #1e293b; }
.stat-label { font-size: 0.75rem; color: #64748b; margin-top: 0.25rem; }
.stat-ok .stat-value { color: #16a34a; }
.stat-err .stat-value { color: #dc2626; }
.stat-cache .stat-value { color: #7c3aed; }

/* ── Section ── */
.section-title { font-size: 0.875rem; font-weight: 600; color: #475569; margin-bottom: 0.75rem; }

/* ── Anomalies ── */
.anomaly-list { display: flex; flex-direction: column; gap: 0.5rem; }
.anomaly-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
}
.sev-critical { background: #fef2f2; border-left: 4px solid #dc2626; }
.sev-warning  { background: #fffbeb; border-left: 4px solid #f59e0b; }
.sev-info     { background: #eff6ff; border-left: 4px solid #3b82f6; }
.anomaly-badge {
  font-size: 0.7rem; font-weight: 700;
  padding: 0.2rem 0.5rem; border-radius: 4px;
  background: rgba(0,0,0,0.08); white-space: nowrap;
}
.anomaly-inv  { font-weight: 600; white-space: nowrap; }
.anomaly-desc { flex: 1; color: #475569; }
.anomaly-amt  { font-weight: 600; white-space: nowrap; }

/* ── Tables ── */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
thead th {
  text-align: left;
  padding: 0.6rem 0.75rem;
  font-size: 0.75rem; font-weight: 600; color: #64748b;
  border-bottom: 1px solid #e2e8f0;
  white-space: nowrap;
  background: #f8fafc;
}
tbody td { padding: 0.6rem 0.75rem; border-bottom: 1px solid #f1f5f9; color: #334155; }
.mono { font-family: monospace; font-size: 0.82rem; }
.text-right { text-align: right; }
.neg { color: #dc2626; }

/* ── Trial Balance ── */
.acct-name { font-weight: 500; }
.acct-type { color: #94a3b8; font-size: 0.8rem; }
tfoot td {
  padding: 0.6rem 0.75rem;
  border-top: 2px solid #e2e8f0;
  font-weight: 700;
  color: #1e293b;
}
.total-row { background: #f8fafc; }
.badge-ok  { background: #dcfce7; color: #166534; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
.badge-err { background: #fee2e2; color: #991b1b; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }

/* ── Invoice rows ── */
.inv-row { cursor: pointer; user-select: none; transition: background 0.1s; }
.inv-row:hover { background: #f8fafc; }
.row-anomaly td { background: #fffbeb; }
.row-expanded td { background: #eff6ff !important; font-weight: 500; }
.chevron { color: #94a3b8; font-size: 0.75rem; text-align: center; padding: 0.6rem 0.5rem; }
.source { color: #94a3b8; font-size: 0.8rem; }
.conf-badge {
  padding: 0.15rem 0.5rem; border-radius: 4px;
  font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
}
.conf-high   { background: #dcfce7; color: #166534; }
.conf-medium { background: #fef9c3; color: #854d0e; }
.conf-low    { background: #fee2e2; color: #991b1b; }

/* ── Journal entries expand ── */
.entries-row td { padding: 0; border-bottom: 2px solid #bfdbfe; }
.entries-cell { background: #f0f9ff; }
.entries-wrap { padding: 1rem 1.5rem 1rem 2.5rem; }
.entries-header { font-size: 0.75rem; font-weight: 700; color: #1e40af; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }
.entries-table { width: 100%; border-collapse: collapse; }
.entries-table th {
  text-align: left; padding: 0.35rem 0.75rem;
  font-size: 0.72rem; font-weight: 600; color: #3b82f6;
  border-bottom: 1px solid #bfdbfe; background: transparent;
}
.entries-table td { padding: 0.35rem 0.75rem; font-size: 0.82rem; border-bottom: 1px solid #e0f2fe; color: #1e3a5f; }
.e-account { font-weight: 600; }
.e-type  { color: #64748b; font-size: 0.78rem; }
.e-desc  { color: #475569; }
.e-amt   { color: #1e40af; font-weight: 600; }

.entry-anomalies { display: flex; flex-direction: column; gap: 0.3rem; margin-top: 0.75rem; }
.anomaly-tag {
  font-size: 0.78rem; padding: 0.25rem 0.75rem; border-radius: 6px; font-weight: 500;
}
</style>
