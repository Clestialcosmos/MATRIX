const markSheet = '/brand/matrix-mark.jpg'

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <a className={`brand ${compact ? 'brand--compact' : ''}`} href="/" aria-label="MATRIX home">
      <span className="brand__mark" style={{ backgroundImage: `url(${markSheet})` }} aria-hidden="true" />
      {!compact && <span className="brand__word">MATRIX</span>}
    </a>
  )
}
