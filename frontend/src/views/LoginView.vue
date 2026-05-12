<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import kratos from '../pkg/kratos'
import type { UiNodeInputAttributes } from '@ory/client'

const route = useRoute()
const flowAction = ref('')
const csrfToken = ref('')
const loading = ref(true)
const formError = ref<string | null>(null)

onMounted(async () => {
  const flowId = route.query.flow as string | undefined
  if (!flowId) {
    window.location.href = `${window.location.origin}/self-service/login/browser`
    return
  }
  try {
    const { data } = await kratos.getLoginFlow({ id: flowId })
    flowAction.value = data.ui.action
    const csrf = data.ui.nodes.find(
      n => (n.attributes as UiNodeInputAttributes).name === 'csrf_token',
    )
    csrfToken.value = (csrf?.attributes as UiNodeInputAttributes)?.value ?? ''

    // Surface any error messages Kratos put in the flow (e.g. wrong password)
    const msgs = data.ui.messages ?? []
    if (msgs.length) formError.value = msgs.map(m => m.text).join(' ')
  } catch {
    formError.value = 'Session expired — restarting…'
    setTimeout(() => {
      window.location.href = `${window.location.origin}/self-service/login/browser`
    }, 1200)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <span class="brand-icon">📊</span>
        <h1 class="brand-name">Finance Bot</h1>
        <p class="brand-sub">AI-powered invoice reconciliation</p>
      </div>

      <div class="login-desc">
        <p class="desc-intro">
          Month-end reconciliation is slow, error-prone, and hard to audit.
          Finance Bot automates the entire pipeline:
        </p>
        <ul class="feature-list">
          <li>Sync invoices from Odoo or upload PDF / CSV files</li>
          <li>AI classifies each expense into the correct account</li>
          <li>Generates double-entry journal entries automatically</li>
          <li>Detects duplicates, large amounts, and future-dated invoices</li>
          <li>Ask questions in plain English — "How much did we spend on marketing?"</li>
          <li>Export a ready-to-use Excel reconciliation report</li>
        </ul>
      </div>

      <div v-if="loading" class="status-msg">Loading…</div>
      <div v-else-if="formError && !flowAction" class="status-msg err">{{ formError }}</div>

      <form v-else :action="flowAction" method="POST" class="login-form">
        <input type="hidden" name="csrf_token" :value="csrfToken" />

        <div v-if="formError" class="field-error">{{ formError }}</div>

        <div class="field">
          <label for="identifier">Email</label>
          <input id="identifier" type="email" name="identifier" autocomplete="email" required />
        </div>

        <div class="field">
          <label for="password">Password</label>
          <input id="password" type="password" name="password" autocomplete="current-password" required />
        </div>

        <input type="hidden" name="method" value="password" />

        <button type="submit" class="btn-submit">Sign in</button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8fafc;
}
.login-card {
  width: 100%;
  max-width: 380px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  box-shadow: 0 4px 24px rgba(0,0,0,0.06);
}
.login-brand {
  text-align: center;
}
.brand-icon { font-size: 2rem; }
.brand-name {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0.25rem 0 0;
}
.brand-sub { font-size: 0.8rem; color: #94a3b8; margin: 0.2rem 0 0; }
.status-msg { text-align: center; font-size: 0.875rem; color: #64748b; }
.status-msg.err { color: #dc2626; }
.login-form { display: flex; flex-direction: column; gap: 1rem; }
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.field label { font-size: 0.8rem; font-weight: 600; color: #475569; }
.field input {
  padding: 0.55rem 0.75rem;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.875rem;
  outline: none;
  transition: border-color 0.15s;
}
.field input:focus { border-color: #3b82f6; }
.field-error {
  padding: 0.5rem 0.75rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #dc2626;
  font-size: 0.8rem;
}
.btn-submit {
  padding: 0.65rem;
  background: #3b82f6;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
  margin-top: 0.25rem;
}
.btn-submit:hover { background: #2563eb; }
.login-desc {
  padding: 0.75rem 0.5rem;
  border-top: 1px solid #f1f5f9;
  border-bottom: 1px solid #f1f5f9;
}
.desc-intro {
  font-size: 0.8rem;
  color: #475569;
  line-height: 1.5;
  margin: 0 0 0.6rem;
  text-align: center;
}
.feature-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.feature-list li {
  font-size: 0.78rem;
  color: #64748b;
  padding-left: 1.1rem;
  position: relative;
  line-height: 1.4;
}
.feature-list li::before {
  content: '✓';
  position: absolute;
  left: 0;
  color: #22c55e;
  font-weight: 700;
  font-size: 0.7rem;
  top: 0.05rem;
}
</style>
