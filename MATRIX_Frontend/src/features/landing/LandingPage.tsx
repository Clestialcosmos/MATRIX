import { useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowRight, ArrowUpRight, Check, ChevronRight, Play, Sparkles } from 'lucide-react'
import { Link } from 'react-router'
import { Brand } from '../../components/Brand'

const INTRO_SEEN = 'matrix-intro-seen-v1'

export function LandingPage() {
  const [showIntro, setShowIntro] = useState(() => {
    try { return !sessionStorage.getItem(INTRO_SEEN) } catch { return true }
  })
  const [autoplayFailed, setAutoplayFailed] = useState(false)
  const [reducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const videoRef = useRef<HTMLVideoElement>(null)
  const autoplayAttempted = useRef(false)

  useEffect(() => {
    if (!showIntro) return
    document.body.classList.add('intro-active')
    return () => document.body.classList.remove('intro-active')
  }, [showIntro])

  useEffect(() => {
    if (!showIntro || reducedMotion || !videoRef.current || autoplayAttempted.current) return
    autoplayAttempted.current = true
    videoRef.current.play().catch(() => setAutoplayFailed(true))
  }, [showIntro, reducedMotion])

  const finishIntro = () => {
    sessionStorage.setItem(INTRO_SEEN, 'true')
    setShowIntro(false)
  }

  return <>
    {!showIntro && <div className="landing-page">
      <header className="landing-nav"><Brand /><nav><a href="#platform">Platform</a><a href="#products">Products</a><Link className="landing-login" to="/login">Log in</Link><Link className="button button--small" to="/register">Get started <ArrowRight size={15} /></Link></nav></header>
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero__ambient" />
        <div className="hero__copy"><div className="eyebrow"><span className="eyebrow__line" /> INTELLIGENCE, IN MOTION</div><div className="hero__telemetry" aria-hidden="true">FIELD M-01&nbsp; / &nbsp;SECTOR 07&nbsp; / &nbsp;VECTOR 2.40</div><h1 id="hero-title">INTELLIGENCE<br />BEFORE EVERY<br /><span>LAUNCH.</span></h1><p className="hero__descriptor">PRODUCT MARKET INTELLIGENCE PLATFORM</p><p className="hero__summary">Clarity for the next big move. Bring market signals, product research, and launch planning into focus.</p><div className="hero__actions"><Link className="button" to="/register">Explore MATRIX <ArrowRight size={16} /></Link><Link className="text-button" to="/login">Sign in <ArrowUpRight size={15} /></Link></div><div className="hero__proof"><span className="proof-icon"><Check size={12} /></span> Designed for confident product decisions</div></div>
        <GlobeArt />
        <div className="hero__scroll"><span>SCROLL TO EXPLORE</span><ArrowDown size={14} /></div>
      </section>
      <section id="platform" className="platform-section"><div className="section-kicker">ONE PLATFORM, CLEARER SIGNALS</div><div className="platform-section__heading"><h2>Turn possibility<br />into a plan.</h2><p>Move from the first market question to an informed next step with a focused intelligence workspace.</p></div><div id="products" className="product-cards"><article className="product-card product-card--premium"><div className="product-card__icon"><Sparkles size={20} /></div><div className="product-card__tag">INTELLIGENCE</div><h3>MATRIX Premium</h3><p>Research a market, assess risk, and bring launch intelligence into focus.</p><Link to="/premium">Explore Premium <ChevronRight size={16} /></Link><span className="product-card__shine" /></article></div></section>
      <footer className="landing-footer"><Brand /><span>Intelligence before every launch.</span><small>© MATRIX · Product Market Intelligence</small></footer>
    </div>}
    {showIntro && <div className="intro-overlay" role="dialog" aria-label="MATRIX introduction">{!reducedMotion && <video ref={videoRef} className="intro-video" src="/media/matrix-intro.mp4" muted playsInline preload="auto" onEnded={finishIntro} onError={() => setAutoplayFailed(true)} />}<div className="intro-overlay__shade" /><div className="intro-controls">{autoplayFailed && <button className="intro-play" onClick={() => videoRef.current?.play().then(() => setAutoplayFailed(false)).catch(() => setAutoplayFailed(true))}><Play size={14} fill="currentColor" /> Play intro</button>}<button className="intro-skip" onClick={finishIntro}>Skip intro <ArrowRight size={14} /></button></div>{reducedMotion && <div className="intro-reduced">Cinematic motion reduced based on your system preference. <button onClick={finishIntro}>Continue <ArrowRight size={14} /></button></div>}</div>}
  </>
}

function GlobeArt() {
  const nodes = [[215,88],[277,99],[332,144],[360,218],[318,309],[250,344],[180,315],[130,262],[124,192],[161,132],[245,186],[291,227],[206,246],[267,273],[166,207],[319,176]]
  return <div className="globe-art" aria-hidden="true"><div className="globe-art__halo" /><svg className="globe-art__svg" viewBox="0 0 480 480"><defs><radialGradient id="planetFill" cx="38%" cy="32%"><stop stopColor="#163b75" stopOpacity=".6" /><stop offset=".8" stopColor="#071227" stopOpacity=".86" /><stop offset="1" stopColor="#020612" /></radialGradient><linearGradient id="planetEdge"><stop stopColor="#41ddff" /><stop offset=".47" stopColor="#716fff" /><stop offset="1" stopColor="#00b9ff" /></linearGradient><filter id="glow"><feGaussianBlur stdDeviation="3" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter><clipPath id="planetClip"><circle cx="240" cy="240" r="167" /></clipPath></defs><circle cx="240" cy="240" r="196" fill="none" stroke="#4861b4" strokeOpacity=".18" /><circle cx="240" cy="240" r="180" fill="none" stroke="#4e95e8" strokeOpacity=".22" /><circle cx="240" cy="240" r="167" fill="url(#planetFill)" stroke="url(#planetEdge)" strokeWidth="2" filter="url(#glow)"/><g clipPath="url(#planetClip)" fill="none" stroke="#4ba9f7" strokeOpacity=".32"><ellipse cx="240" cy="240" rx="104" ry="167"/><ellipse cx="240" cy="240" rx="45" ry="167"/><ellipse cx="240" cy="240" rx="167" ry="54"/><ellipse cx="240" cy="240" rx="167" ry="109"/><path d="M82 174c84 43 224 39 316-8M74 299c94-43 236-34 326 13"/></g><g clipPath="url(#planetClip)">{nodes.map(([x,y],i)=><circle key={`${x}-${y}`} cx={x} cy={y} r={i%4===0?3:1.8} fill={i%3===0?'#d9f6ff':'#45d9ff'} opacity={i%4===0?'.92':'.64'} />)}<path d="M129 264 166 207 215 88 277 99 332 144 319 176 360 218 291 227 267 273 250 344 180 315 130 262" stroke="#559eff" strokeOpacity=".55" strokeWidth=".7" fill="none"/><path d="M166 207 245 186 319 176M166 207l41 39 84-19 38 42m-83-12-28 78" stroke="#a08cff" strokeOpacity=".52" strokeWidth=".8" fill="none"/>{nodes.filter((_,i)=>i%3===0).map(([x,y])=><circle key={`pulse-${x}-${y}`} cx={x} cy={y} r="5" fill="#51dfff" opacity=".2" />)}</g><path d="M130 290c57 39 172 39 222-7" fill="none" stroke="#4df1ff" strokeOpacity=".8" strokeWidth="2" filter="url(#glow)"/><circle cx="179" cy="80" r="3" fill="#d5fdff" filter="url(#glow)"/><circle cx="375" cy="270" r="2" fill="#b69cff" filter="url(#glow)"/></svg><div className="orbit-label orbit-label--top"><i /> MARKET SIGNALS</div><div className="orbit-label orbit-label--bottom"><span>GLOBAL</span><b>INTELLIGENCE</b><ArrowUpRight size={13} /></div><div className="orbit-chip orbit-chip--a"><span className="chip-spark">↗</span><small>MARKET MODEL</small><b>Signal map</b><div className="mini-wave"><i/><i/><i/><i/><i/><i/><i/><i/></div></div><div className="orbit-chip orbit-chip--b"><small>VISUAL PREVIEW</small><b>Illustrative map</b><div className="chip-bars"><i/><i/><i/><i/><i/><i/><i/></div></div><div className="globe-art__cross globe-art__cross--one"/><div className="globe-art__cross globe-art__cross--two"/></div>
}
