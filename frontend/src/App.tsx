import { NavLink, Route, Routes } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Settings from './pages/Settings';

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">📈 AI Stocks &amp; News</span>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </header>
      <p className="disclaimer">
        Decision support only — not financial advice. LLM output can be wrong; historical markers are
        retrospective reasoning, not a backtested strategy.
      </p>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
