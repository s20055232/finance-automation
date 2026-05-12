import { Configuration, FrontendApi } from '@ory/client'

// All Kratos calls go through Oathkeeper so they are same-origin with the app.
// Using window.location.origin works for both local (http://127.0.0.1:4455)
// and external access (Cloudflare Tunnel, production URL).
const kratos = new FrontendApi(
  new Configuration({
    basePath: window.location.origin,
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
  return `${window.location.origin}/self-service/login/browser`
}

export async function logout(): Promise<void> {
  const { data } = await kratos.createBrowserLogoutFlow()
  window.location.href = data.logout_url
}
