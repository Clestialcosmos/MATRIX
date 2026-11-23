import { createClient } from '@supabase/supabase-js'
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined
export const configReady = Boolean(supabaseUrl && supabaseAnonKey && import.meta.env.VITE_FASTAPI_BASE_URL)
export const supabase = supabaseUrl && supabaseAnonKey ? createClient(supabaseUrl, supabaseAnonKey, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } }) : null
export const apiBase = (import.meta.env.VITE_FASTAPI_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
 if (!supabase) throw new Error('Supabase frontend configuration is missing. Fill the VITE_ values in .env.')
 const { data } = await supabase.auth.getSession(); if (!data.session?.access_token) throw new Error('Please sign in again.')
 const response = await fetch(`${apiBase}${path}`, { ...init, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${data.session.access_token}`, ...(init.headers || {}) } })
 const payload = await response.json().catch(() => ({})); if (!response.ok) { const d=payload?.detail; throw new Error(typeof d==='string'?d:d?.message||payload?.error?.message||`Request failed (${response.status}).`) } return payload as T
}
