<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import NavBar from './components/NavBar.vue'
import { getSession, loginUrl, type KratosSession } from './pkg/kratos'

const route = useRoute()
const session = ref<KratosSession | null>(null)
const checking = ref(true)

onMounted(async () => {
  session.value = await getSession()
  checking.value = false
  if (!session.value && route.path !== '/login') {
    window.location.href = loginUrl()
  }
})
</script>

<template>
  <div v-if="checking" class="splash">Checking session…</div>

  <template v-else>
    <template v-if="session">
      <NavBar :email="session.identity.traits.email" />
      <main class="main-content">
        <RouterView />
      </main>
    </template>

    <!-- unauthenticated: only login page is shown, no NavBar -->
    <RouterView v-else />
  </template>
</template>

<style scoped>
.splash {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  color: #94a3b8;
  font-size: 0.875rem;
}
.main-content {
  max-width: 1100px;
  margin: 0 auto;
  padding: 2rem 1.5rem;
}
</style>
