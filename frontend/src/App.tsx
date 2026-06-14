import { lazy, Suspense } from 'react';
import { Link, NavLink, Route, Routes } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Portfolio from './pages/Portfolio';
import Discover from './pages/Discover';
import Settings from './pages/Settings';
import Evaluation from './pages/Evaluation';
import Chat from './pages/Chat';
import { RunIndicator } from './components/RunIndicator';
import { ThemeToggle } from './components/ThemeToggle';
import { DashboardStateProvider } from './state/dashboardState';
import { WatchlistRunProvider } from './state/watchlistRunState';
import { ChatProvider } from './state/chatState';

const Graph = lazy(() => import('./pages/Graph'));

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? 'nav-link active' : 'nav-link';

export default function App() {
  return (
    <DashboardStateProvider>
    <WatchlistRunProvider>
    <ChatProvider>
      <div className="app">
        <header className="masthead">
          <Link className="brand" to="/">
            <span className="brand-mark">◆</span>
            <span className="brand-name">
              MarketCortex
            </span>
          </Link>
          <RunIndicator />
          <nav className="nav">
            <NavLink to="/" end className={navClass}>Dashboard</NavLink>
            <NavLink to="/portfolio" className={navClass}>Portfolio</NavLink>
            <NavLink to="/discover" className={navClass}>Discover</NavLink>
            <NavLink to="/graph" className={navClass}>Graph</NavLink>
            <NavLink to="/evaluation" className={navClass}>Evaluation</NavLink>
            <NavLink to="/chat" className={navClass}>Chat</NavLink>
            <NavLink to="/settings" className={navClass}>Settings</NavLink>
          </nav>
          <ThemeToggle />
        </header>
        <div className="masthead-rule" />
        <main className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/discover" element={<Discover />} />
            <Route path="/graph" element={<Suspense fallback={<p className="muted">Loading graph…</p>}><Graph /></Suspense>} />
            <Route path="/evaluation" element={<Evaluation />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </ChatProvider>
    </WatchlistRunProvider>
    </DashboardStateProvider>
  );
}
