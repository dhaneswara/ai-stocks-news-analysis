import { afterEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ThemeToggle } from './ThemeToggle';
import { applyTheme } from '../lib/theme';

afterEach(() => {
  applyTheme('gold');
  localStorage.clear();
});

describe('ThemeToggle', () => {
  it('shows the current theme and flips it on click', () => {
    applyTheme('gold');
    render(<ThemeToggle />);
    const btn = screen.getByRole('button', { name: /theme/i });
    expect(document.documentElement.getAttribute('data-theme')).toBe('gold');
    fireEvent.click(btn);
    expect(document.documentElement.getAttribute('data-theme')).toBe('neon');
    fireEvent.click(btn);
    expect(document.documentElement.getAttribute('data-theme')).toBe('gold');
  });
});
