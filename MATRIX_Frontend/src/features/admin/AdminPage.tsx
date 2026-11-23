import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, RefreshCw, ShieldCheck, UserCheck, KeyRound } from 'lucide-react'
import { AppShell } from '../../components/AppShell'
import { apiRequest } from '../../lib/client'

type AdminProfile = { user_id: string; full_name: string | null; access_status: string }
type AdminResponse = { user_id: string; expires_at: string; email_delivery: 'accepted' }

export function AdminPage() {
  const [pending, setPending] = useState<AdminProfile[]>([])
  const [awaiting, setAwaiting] = useState<AdminProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [notAdmin, setNotAdmin] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(''); setNotice(''); setNotAdmin(false)
    try {
      const [pendingRows, awaitingRows] = await Promise.all([
        apiRequest<AdminProfile[]>('/api/v1/admin/profiles/pending?limit=100&offset=0'),
        apiRequest<AdminProfile[]>('/api/v1/admin/profiles/approved-awaiting-activation?limit=100&offset=0'),
      ])
      setPending(pendingRows); setAwaiting(awaitingRows)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Could not load administrator data.'
      if (/administrator authorization|required|403/i.test(message)) setNotAdmin(true)
      else setError(message)
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  async function approve(userId: string) {
    setBusyId(userId); setError(''); setNotice('')
    try {
      await apiRequest<AdminProfile>(`/api/v1/admin/profiles/${userId}/approve`, { method: 'POST' })
      setNotice('Account approved. It is now in the activation queue.')
      await load()
    } catch (e) { setError(e instanceof Error ? e.message : 'Approval failed.') }
    finally { setBusyId(null) }
  }

  async function issueCode(userId: string) {
    setBusyId(userId); setError(''); setNotice('')
    try {
      const result = await apiRequest<AdminResponse>(`/api/v1/admin/profiles/${userId}/activation-code`, { method: 'POST' })
      setNotice(`Activation email accepted for delivery. Code expires ${new Date(result.expires_at).toLocaleString()}.`)
      await load()
    } catch (e) { setError(e instanceof Error ? e.message : 'Activation code could not be issued.') }
    finally { setBusyId(null) }
  }

  return <AppShell section="Manage"><div className="page-heading"><div><div className="eyebrow">SECURE ADMINISTRATION</div><h1>Admin Portal</h1><p>Review new accounts and issue activation codes through the protected MATRIX backend.</p></div><button className="outline-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15}/> Refresh</button></div>
    {notAdmin ? <section className="admin-access-locked"><ShieldCheck size={24}/><h2>This account is not configured as MATRIX admin.</h2><p>Set <code>MATRIX_ADMIN_USER_ID</code> in the backend .env to this signed-in account's Supabase Auth User ID (UUID), then restart the backend and sign in again.</p></section> : null}
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="success" role="status"><CheckCircle2 size={16}/> {notice}</p>}
    {!notAdmin && <><div className="admin-stat-grid"><article className="admin-stat"><span className="panel-icon panel-icon--blue"><UserCheck size={17}/></span><span className="eyebrow">PENDING APPROVAL</span><b>{loading?'…':pending.length}</b><small>Accounts awaiting review</small></article><article className="admin-stat"><span className="panel-icon panel-icon--violet"><KeyRound size={17}/></span><span className="eyebrow">AWAITING ACTIVATION</span><b>{loading?'…':awaiting.length}</b><small>Approved accounts needing a code</small></article></div>
      <section className="admin-content-card"><div className="admin-content-card__head"><div><h2>Pending accounts</h2><p>Approve an account to make it eligible for activation.</p></div></div>{loading ? <p>Loading protected admin data…</p> : pending.length===0 ? <p>No accounts are currently pending approval.</p> : <div className="admin-profile-list">{pending.map(profile=><article className="admin-profile-row" key={profile.user_id}><div><b>{profile.full_name || 'Unnamed user'}</b><small>{profile.user_id}</small><span className="subtle-badge">{profile.access_status}</span></div><button className="button button--small" disabled={busyId===profile.user_id} onClick={()=>void approve(profile.user_id)}>{busyId===profile.user_id?'Working…':'Approve'}</button></article>)}</div>}</section>
      <section className="admin-content-card"><div className="admin-content-card__head"><div><h2>Approved · awaiting activation</h2><p>Issue the existing activation email. The code is not shown in this dashboard.</p></div></div>{loading ? <p>Loading…</p> : awaiting.length===0 ? <p>No approved accounts are awaiting activation.</p> : <div className="admin-profile-list">{awaiting.map(profile=><article className="admin-profile-row" key={profile.user_id}><div><b>{profile.full_name || 'Unnamed user'}</b><small>{profile.user_id}</small><span className="subtle-badge">Approved</span></div><button className="button button--small" disabled={busyId===profile.user_id} onClick={()=>void issueCode(profile.user_id)}>{busyId===profile.user_id?'Sending…':'Issue activation code'}</button></article>)}</div>}</section></>}
  </AppShell>
}
