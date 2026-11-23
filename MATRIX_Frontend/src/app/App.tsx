import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { AccountPage, PremiumPage, ReportsPage } from '../features/products/ProductPages'
import { AuthPage, ForgotPasswordPage, VerifyEmailPage } from '../features/auth/AuthPages'
import { DashboardPage } from '../features/dashboard/DashboardPage'
import { AdminPage } from '../features/admin/AdminPage'
import { LandingPage } from '../features/landing/LandingPage'
import { AccessRequestPage, AccessStatusPage, ActivationCodePage } from '../features/access/AccessPages'
import { AppShell } from '../components/AppShell'
import { ArrowRight, KeyRound, LockKeyhole } from 'lucide-react'
import { Link } from 'react-router'
import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { supabase, apiRequest } from '../lib/client'

function useMatrixAccess() {
 const [state,setState]=useState<{loading:boolean;access:boolean;loggedIn:boolean}>({loading:true,access:false,loggedIn:false})
 useEffect(()=>{let alive=true;async function load(){try{const session=(await supabase?.auth.getSession())?.data.session;if(!session){if(alive)setState({loading:false,access:false,loggedIn:false});return}const result=await apiRequest<{has_matrix_access:boolean}>('/api/v1/me/access');if(alive)setState({loading:false,access:!!result.has_matrix_access,loggedIn:true})}catch{if(alive)setState({loading:false,access:false,loggedIn:!!(await supabase?.auth.getSession())?.data.session})}};void load();const sub=supabase?.auth.onAuthStateChange(()=>void load()).data.subscription;return()=>{alive=false;sub?.unsubscribe()}},[])
 return state
}
function ProtectedPreviewRoute({ product, children }: { product: string; children: ReactNode }) {
 const state=useMatrixAccess()
 if(state.loading)return <div className="auth-main"><p>Checking MATRIX access…</p></div>
 return state.access?children:<ProductAccessPending product={product}/>
}

function ProductAccessPending({ product }: { product: string }) {
  return <AppShell section="Access"><section className="product-access-pending"><span className="product-access-pending__icon"><LockKeyhole size={22}/></span><div className="eyebrow">PRODUCT ACCESS</div><h1>{product} is pending activation</h1><p>Product access has not been confirmed for this preview account. Signing in alone does not unlock protected intelligence, reports, or dashboard data.</p><div className="product-access-pending__actions"><Link className="button button--small" to="/login">Sign in</Link><Link className="outline-button" to="/access-status">Check activation status <ArrowRight size={15}/></Link><Link className="outline-button" to="/request-access">Request access</Link><Link className="text-button" to="/activate"><KeyRound size={14}/> Enter activation code</Link></div><span className="subtle-badge">SERVER-VERIFIED ACCESS REQUIRED</span></section></AppShell>
}

export function App() {
  return <BrowserRouter><Routes>
    <Route path="/" element={<LandingPage/>}/>
    <Route path="/login" element={<AuthPage initialMode="login"/>}/>
    <Route path="/register" element={<AuthPage initialMode="register"/>}/>
    <Route path="/forgot-password" element={<ForgotPasswordPage/>}/>
    <Route path="/verify-email" element={<VerifyEmailPage/>}/>
    <Route path="/access-status" element={<AccessStatusPage/>}/>
    <Route path="/request-access" element={<AccessRequestPage/>}/>
    <Route path="/activate" element={<ActivationCodePage/>}/>
    <Route path="/dashboard" element={<ProtectedPreviewRoute product="Dashboard intelligence"><DashboardPage/></ProtectedPreviewRoute>}/>
    <Route path="/premium" element={<ProtectedPreviewRoute product="MATRIX Premium"><PremiumPage/></ProtectedPreviewRoute>}/>
    <Route path="/premium/reports" element={<ProtectedPreviewRoute product="MATRIX Premium reports"><PremiumPage view="reports"/></ProtectedPreviewRoute>}/>
    <Route path="/reports" element={<ProtectedPreviewRoute product="Reports"><ReportsPage/></ProtectedPreviewRoute>}/>
    <Route path="/account" element={<AccountPage/>}/>
    <Route path="/admin" element={<AdminPage/>}/>
    <Route path="*" element={<Navigate to="/" replace/>}/>
  </Routes></BrowserRouter>
}
