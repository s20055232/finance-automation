import { Configuration, FrontendApi } from '@ory/client'

// All Kratos calls go through Oathkeeper (127.0.0.1:4455) so they are
// same-origin with the app. Direct calls to localhost:4433 are cross-site
// (localhost ≠ 127.0.0.1), causing SameSite=Lax cookies to be blocked in XHR.
const kratos = new FrontendApi(
  new Configuration({
    basePath: 'http://127.0.0.1:4455',
    baseOptions: { withCredentials: true },
  }),
)

export default kratos

export interface KratosSession {
  id: string
  identity: {
    id: string
    traits: { email?: string; name?: string }
  }
}

export async function getSession(): Promise<KratosSession | null> {
  try {
    const { data } = await kratos.toSession()
    return data as KratosSession
  } catch {
    return null
  }
}

export function loginUrl(): string {
  return 'http://127.0.0.1:4455/self-service/login/browser'
}

export async function logout(): Promise<void> {
  const { data } = await kratos.createBrowserLogoutFlow()
  window.location.href = data.logout_url
}
