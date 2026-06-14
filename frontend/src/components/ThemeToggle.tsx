import { useTheme, type ThemeName } from '../lib/theme';

const NEXT: Record<ThemeName, ThemeName> = { gold: 'neon', neon: 'gold' };
const LABEL: Record<ThemeName, string> = { gold: 'Gold', neon: 'Neon' };

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <button
      type="button"
      className="theme-toggle"
      aria-label={`Theme: ${LABEL[theme]}. Switch to ${LABEL[NEXT[theme]]}.`}
      title={`Switch to ${LABEL[NEXT[theme]]} theme`}
      onClick={() => setTheme(NEXT[theme])}
    >
      ◑ {LABEL[theme]}
    </button>
  );
}
