import { Link, NavLink, Route, Routes } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Discover from './pages/Discover';
import Settings from './pages/Settings';

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? 'nav-link active' : 'nav-link';

export default function App() {
  return (
    <div className="app">
      <header className="masthead">
        <Link className="brand" to="/">
          <span className="brand-mark">◆</span>
          <span className="brand-name">
            AI Stocks <span className="amp">&amp;</span> News
          </span>
        </Link>
        <nav className="nav">
          <NavLink to="/" end className={navClass}>Dashboard</NavLink>
          <NavLink to="/discover" className={navClass}>Discover</NavLink>
          <NavLink to="/settings" className={navClass}>Settings</NavLink>
        </nav>
      </header>
      <div className="masthead-rule" />
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/discover" element={<Discover />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
