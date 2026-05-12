import { reactive } from 'vue'
import type { OdooStatus, ReconciliationResult } from '../api/client'

// Module-level reactive — persists across route changes for the app's lifetime
const state = reactive({
  odooStatus:   null as OdooStatus | null,
  result:       null as ReconciliationResult | null,
  loading:      false,
  error:        null as string | null,
  question:     '',
  queryAnswer:  null as string | null,
  queryLoading: false,
  queryError:   null as string | null,
})

export function useDashboard() {
  return state
}
