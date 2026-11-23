import type { FormEvent } from 'react'
import { useState, useEffect, useRef } from 'react'
import { ArrowRight, BarChart3, CheckCircle2, Clock, FileText, Lightbulb, LockKeyhole, Microscope, ShieldAlert, XCircle } from 'lucide-react'
import { AppShell } from '../../components/AppShell'
import { apiRequest } from '../../lib/client'

const premiumFeatures = [
  { title: 'Market research', icon: Microscope, description: 'Real-time Brave Search research on your target market, competitors, and industry trends.' },
  { title: 'Risk assessment', icon: ShieldAlert, description: 'AI-synthesised risk indicators across market, financial, and operational dimensions.' },
  { title: 'Financial simulation', icon: BarChart3, description: 'Base, optimistic, and downside scenario comparison from your actual inputs.' },
  { title: 'Final recommendation', icon: Lightbulb, description: 'Agentic AI decision synthesis with GO / CONDITIONAL GO / NO GO recommendation.' },
]

/** Render the decision badge with appropriate colour */
function DecisionBadge({ decision }: { decision: string }) {
  const upper = decision.toUpperCase()
  const isGo = /\bGO\b/.test(upper) && !/NO\s+GO/.test(upper)
  const isNoGo = /NO\s*GO/.test(upper)
  const cls = isGo ? 'decision-badge decision-badge--go' : isNoGo ? 'decision-badge decision-badge--nogo' : 'decision-badge decision-badge--conditional'
  return <span className={cls}>{decision}</span>
}

/** Inline summary panel rendered after a successful assessment */
function AssessmentResultCard({ result, assessmentId }: { result: any; assessmentId: string }) {
  const decisionRaw: string =
    result?.decision_report ?? result?.decision ?? result?.final_decision ?? result?.report_text ?? ''
  const decisionMatch = decisionRaw.match(/\b(CONDITIONAL\s+GO|NO\s+GO|GO|DEFER|LAUNCH|DO\s+NOT\s+LAUNCH)\b/i)
  const decision = decisionMatch ? decisionMatch[1].toUpperCase() : 'See decision analysis'
  const confidenceMatch = decisionRaw.match(/confidence\s*[:=-]\s*([A-Za-z]+)/i)
  const confidence = confidenceMatch ? confidenceMatch[1].toUpperCase() : null
  // Extract first meaningful paragraph after decision line
  const lines = decisionRaw.split('\n').filter(Boolean)
  const summaryLine = lines.find(l => l.length > 60 && !l.startsWith('#') && !l.match(/^\*\*(GO|NO|CONDITIONAL|DEFER)/i)) ?? ''

  return (
    <div className="assessment-result-card">
      <div className="assessment-result-card__header">
        <span className="panel-icon panel-icon--violet"><CheckCircle2 size={18} /></span>
        <div>
          <div className="eyebrow">ASSESSMENT COMPLETE</div>
          <h3>AI Decision Result</h3>
        </div>
      </div>
      <div className="assessment-result-card__decision">
        <DecisionBadge decision={decision} />
        {confidence && <span className="confidence-label">Confidence: {confidence}</span>}
      </div>
      {summaryLine && (
        <p className="assessment-result-card__summary">
          {summaryLine.replace(/^[*#\s-]+/, '')}
        </p>
      )}
      <div className="assessment-result-card__meta">
        <small>Assessment ID: {assessmentId}</small>
      </div>
    </div>
  )
}

export function PremiumPage({ view = 'overview' }: { view?: string }) {
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [result, setResult] = useState<any>(null)
  const [history, setHistory] = useState<any[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (view === 'reports') {
      void apiRequest<{ items: any[] }>('/api/v1/reports')
        .then(x => setHistory(x.items || []))
        .catch(e => setError(e.message))
    }
  }, [view])

  // Elapsed-time ticker while assessment is running
  useEffect(() => {
    if (busy) {
      setElapsed(0)
      timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000)
    } else {
      if (timerRef.current) clearInterval(timerRef.current)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [busy])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const formElement = event.currentTarget
    setBusy(true)
    setMessage('')
    setError('')
    setPendingId(null)
    setResult(null)
    const form = new FormData(formElement)
    const payload = {
      product_name: String(form.get('product_name')),
      target_market: String(form.get('target_market')),
      decision_type: String(form.get('decision_type')),
      currency: String(form.get('currency')),
      product_category: String(form.get('product_category')),
      launch_stage: 'pre_launch',
      planned_selling_price: Number(form.get('planned_selling_price')),
      expected_sales_quantity: Number(form.get('expected_sales_quantity')),
      estimated_unit_cost: Number(form.get('estimated_unit_cost')),
      planned_marketing_budget: Number(form.get('planned_marketing_budget')),
      intended_launch_period: String(form.get('intended_launch_period') || ''),
    }
    try {
      const res = await apiRequest<any>('/api/v1/assessments', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setResult(res.result ?? null)
      setMessage(`Assessment completed. Report ready.`)
      formElement.reset()
    } catch (e) {
      if (e instanceof Error) {
        // Check for timeout response — backend embeds assessment_id in detail
        const timeoutMatch = e.message.match(/workflow_outcome_unknown|timed? ?out/i)
        // The backend 504 error message includes the assessment_id in its detail object.
        // apiRequest surfaces detail.message; check if it contains the id hint.
        const idMatch = e.message.match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i)
        if (idMatch) setPendingId(idMatch[1])
        if (timeoutMatch || idMatch) {
          setError(
            'The Agent Layer is still processing. This typically takes 2–3 minutes. ' +
            (idMatch ? `Assessment ID: ${idMatch[1]} — check history to view the result once complete.` : 'Check your assessment history shortly.')
          )
        } else {
          setError(e.message)
        }
      } else {
        setError('Assessment failed.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (view === 'reports') {
    return (
      <AppShell section="Products">
        <div className="page-heading product-page-heading">
          <div>
            <div className="eyebrow">MATRIX PREMIUM</div>
            <h1>Premium reports</h1>
            <p>Your saved Agentic AI reports.</p>
          </div>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="empty-state-card">
          {history.length === 0
            ? <><h2>No reports yet.</h2><p>Completed reports will appear here after your first successful assessment.</p></>
            : history.map(r => (
              <article key={r.id} className="premium-feature-card">
                <span className="premium-feature-card__icon"><FileText size={18} /></span>
                <div className="eyebrow">ASSESSMENT REPORT</div>
                <h3>Assessment report</h3>
                <p>{new Date(r.created_at).toLocaleString()}</p>
                <button className="outline-button" onClick={async () => {
                  try {
                    const x = await apiRequest<{ url: string }>(`/api/v1/reports/${r.id}/url`)
                    window.open(x.url, '_blank', 'noopener,noreferrer')
                  } catch (e) {
                    setError(e instanceof Error ? e.message : 'Download failed')
                  }
                }}>
                  Open PDF <ArrowRight size={14} />
                </button>
              </article>
            ))}
        </div>
      </AppShell>
    )
  }

  const elapsedWarning = busy && elapsed >= 60

  return (
    <AppShell section="Products">
      <div className="page-heading product-page-heading">
        <div>
          <div className="eyebrow">PRODUCT MARKET INTELLIGENCE</div>
          <h1>MATRIX Premium</h1>
          <p>Research, risk analysis, financial simulation and launch recommendations.</p>
        </div>

      </div>
      <section className="premium-landing-card">
        <section className="premium-assessment">
          <div className="premium-assessment__heading">
            <div>
              <div className="eyebrow">PRODUCT ASSESSMENT</div>
              <h2>Start an assessment</h2>
              <p>Enter the financial assumptions required by the connected Agent Layer.</p>
            </div>
          </div>
          <form className="premium-assessment__form" onSubmit={submit}>
            <div className="premium-assessment__grid">
              <label className="premium-assessment__field">Product name<input name="product_name" required maxLength={200} placeholder="e.g. Northstar" /></label>
              <label className="premium-assessment__field">Target market<input name="target_market" required placeholder="e.g. India" /></label>
              <label className="premium-assessment__field">Decision type
                <select name="decision_type" required defaultValue="">
                  <option value="" disabled>Select</option>
                  <option value="new_product_launch">New product launch</option>
                  <option value="market_expansion">Market expansion</option>
                  <option value="product_improvement">Product improvement</option>
                  <option value="continue_or_discontinue">Continue or discontinue</option>
                </select>
              </label>
              <label className="premium-assessment__field">Currency
                <select name="currency" defaultValue="INR">
                  <option>INR</option><option>USD</option><option>EUR</option>
                  <option>GBP</option><option>CAD</option><option>AUD</option>
                </select>
              </label>
              <label className="premium-assessment__field">Product category<input name="product_category" required placeholder="Any product category" /></label>
              <label className="premium-assessment__field">Launch stage<input value="Pre-launch" disabled /></label>
              <label className="premium-assessment__field">Planned selling price<input name="planned_selling_price" type="number" min="0.01" step="any" required /></label>
              <label className="premium-assessment__field">Expected sales quantity<input name="expected_sales_quantity" type="number" min="0.01" step="any" required /></label>
              <label className="premium-assessment__field">Estimated unit cost<input name="estimated_unit_cost" type="number" min="0" step="any" required /></label>
              <label className="premium-assessment__field">Planned marketing budget<input name="planned_marketing_budget" type="number" min="0" step="any" required /></label>
              <label className="premium-assessment__field">Intended launch period (optional)<input name="intended_launch_period" placeholder="e.g. Q2 2027" /></label>
            </div>
            <div className="premium-assessment__actions">
              <button className="button" type="submit" disabled={busy}>
                {busy ? (
                  <><Clock size={15} /> Running… {elapsed > 0 ? `(${Math.floor(elapsed / 60)}m ${elapsed % 60}s)` : ''}</>
                ) : (
                  <>Start Assessment <ArrowRight size={16} /></>
                )}
              </button>
              {elapsedWarning && (
                <p className="assessment-timing-note" role="status">
                  <Clock size={13} /> The Agent Layer typically takes 2–3 minutes. Please wait — do not close this page or resubmit.
                </p>
              )}
              {message && <p className="success" role="status"><CheckCircle2 size={14} /> {message}</p>}
              {error && (
                <p className="error" role="alert">
                  {pendingId ? <><XCircle size={14} /> {error}</> : error}
                </p>
              )}
            </div>
            <p className="muted">The assessment runs synchronously via the Agent Layer. If a timeout occurs, check your assessment history before resubmitting.</p>
          </form>
        </section>

        {/* Inline result display — shown after a successful assessment */}
        {result && (
          <AssessmentResultCard result={result} assessmentId={message.match(/([0-9a-f-]{36})/i)?.[1] ?? 'completed'} />
        )}

        <div className="premium-feature-grid">
          {premiumFeatures.map(({ title, icon: Icon, description }) => (
            <article className="premium-feature-card" key={title}>
              <span className="premium-feature-card__icon"><Icon size={18} /></span>
              <div className="eyebrow">MATRIX PREMIUM</div>
              <h3>{title}</h3>
              <p>{description}</p>
            </article>
          ))}
        </div>
      </section>
    </AppShell>
  )
}

export function ReportsPage() { return <PremiumPage view="reports" /> }

export function AccountPage() {
  return (
    <AppShell section="Manage">
      <div className="page-heading">
        <div>
          <div className="eyebrow">PROFILE &amp; PREFERENCES</div>
          <h1>Account settings</h1>
          <p>Visual profile menu and account preferences.</p>
        </div>
      </div>
      <div className="account-preview">
        <div className="account-avatar">M</div>
        <div>
          <span className="eyebrow">PREVIEW PROFILE</span>
          <h2>Preview user</h2>
          <p>Profile details will load from your existing account when connected.</p>
        </div>
        <span className="subtle-badge">DEMO</span>
      </div>
      <div className="separate-access-note">
        <LockKeyhole size={16} />
        <span>
          <b>Account connection pending</b>
          <small>Profile IDs, roles, and entitlements are not edited by this preview.</small>
        </span>
      </div>
    </AppShell>
  )
}
