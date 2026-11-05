function App() {
  return (
    <main className="dashboard">
      <header>
        <h1>XAU Trading Platform</h1>
        <p>Trading infrastructure dashboard</p>
      </header>

      <section className="status-grid">
        <article className="status-card">
          <h2>Backend API</h2>
          <p className="status-online">Development</p>
        </article>

        <article className="status-card">
          <h2>Database</h2>
          <p className="status-online">PostgreSQL configured</p>
        </article>

        <article className="status-card">
          <h2>Trading Engine</h2>
          <p>Not initialized</p>
        </article>
      </section>
    </main>
  );
}

export default App;
