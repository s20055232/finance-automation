<script setup lang="ts">
import { useRoute } from 'vue-router'
import { logout } from '../pkg/kratos'

const props = defineProps<{ email?: string }>()
const route = useRoute()

const isActive = (path: string) => route.path.startsWith(path)
const odooUrl = `${window.location.origin}/odoo/accounting`

async function handleLogout() {
  await logout()
}
</script>

<template>
  <nav class="navbar">
    <div class="navbar-brand">
      <span class="brand-icon">📊</span>
      <span class="brand-name">Finance Bot</span>
    </div>
    <div class="navbar-links">
      <RouterLink to="/dashboard" :class="{ active: isActive('/dashboard') }">Dashboard</RouterLink>
      <RouterLink to="/reports" :class="{ active: isActive('/reports') }">Reports</RouterLink>
      <a :href="odooUrl" target="_blank" rel="noopener" class="docs-link">
        Odoo ↗
      </a>
      <a href="https://s20055232.github.io/finance-automation/" target="_blank" rel="noopener" class="docs-link">
        Docs ↗
      </a>
    </div>
    <div class="navbar-user">
      <span class="user-email">{{ props.email ?? 'Guest' }}</span>
      <button class="btn-logout" @click="handleLogout">Logout</button>
    </div>
  </nav>
</template>

<style scoped>
.navbar {
  display: flex;
  align-items: center;
  gap: 2rem;
  padding: 0 1.5rem;
  height: 56px;
  background: #1e293b;
  color: #f1f5f9;
  border-bottom: 1px solid #334155;
}
.navbar-brand {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 700;
  font-size: 1rem;
  letter-spacing: 0.02em;
}
.brand-icon { font-size: 1.2rem; }
.navbar-links {
  display: flex;
  gap: 0.25rem;
  flex: 1;
}
.navbar-links a {
  padding: 0.4rem 0.75rem;
  border-radius: 6px;
  color: #94a3b8;
  text-decoration: none;
  font-size: 0.875rem;
  font-weight: 500;
  transition: background 0.15s, color 0.15s;
}
.navbar-links a:hover, .navbar-links a.active {
  background: #334155;
  color: #f1f5f9;
}
.docs-link { color: #64748b !important; letter-spacing: 0.01em; }
.navbar-user {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.user-email { font-size: 0.8rem; color: #64748b; }
.btn-logout {
  padding: 0.3rem 0.75rem;
  border-radius: 6px;
  border: 1px solid #334155;
  background: transparent;
  color: #94a3b8;
  font-size: 0.8rem;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.btn-logout:hover {
  background: #ef4444;
  border-color: #ef4444;
  color: #fff;
}
</style>
