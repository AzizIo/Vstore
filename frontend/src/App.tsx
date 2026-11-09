export function App() {
  return (
    <main className="app-shell">
      <header className="topbar">
        <span className="brand-mark">V</span>
        <span className="brand-name">VILTARA</span>
        <span className="network-label">TON MARKET</span>
      </header>

      <section className="hero">
        <p className="eyebrow">DIGITAL COLLECTIBLES MARKETPLACE</p>
        <h1>Discover rare<br /><span>digital gifts.</span></h1>
        <p className="hero-copy">
          A curated marketplace for verifiable Telegram collectibles and TON NFTs.
        </p>
        <div className="hero-actions">
          <button className="primary-button" type="button">Explore collection</button>
          <span className="status-pill"><i /> Marketplace preview</span>
        </div>
      </section>

      <section className="notice">
        <strong>Coming together, one verified asset at a time.</strong>
        <p>The marketplace interface is being prepared. Asset verification and safe transfers come first.</p>
      </section>

      <footer>VILTARA SHOP <span>•</span> Built on TON</footer>
    </main>
  );
}
