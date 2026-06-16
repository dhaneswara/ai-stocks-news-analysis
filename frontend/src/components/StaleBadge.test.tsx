import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StaleBadge } from './StaleBadge';

// Pin "now" to Tue 2026-06-16 so the latest completed trading day is Mon 2026-06-15.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-06-16T18:00:00Z'));
});
afterEach(() => {
  vi.useRealTimers();
});

describe('StaleBadge', () => {
  it('shows the pill when the latest bar is behind the last trading day', () => {
    render(<StaleBadge lastDate="2026-06-12" />);
    const badge = screen.getByText(/data lagging/i);
    expect(badge).toBeInTheDocument();
    // tooltip names the actual (UTC-safe) bar date
    expect(badge.getAttribute('title')).toContain('Jun 12, 2026');
  });

  it('renders nothing when the bar is current', () => {
    const { container } = render(<StaleBadge lastDate="2026-06-15" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when there is no bar date', () => {
    const { container } = render(<StaleBadge lastDate={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
