import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { Markdown } from './Markdown';

it('renders bold, code, headings, lists, and links', () => {
  const { container } = render(
    <Markdown text={'## NVDA\n\nA **strong** buy with `RSI` rising.\n\n- one\n- two\n\nSee [docs](https://x.io).'} />,
  );
  expect(container.querySelector('h4')?.textContent).toBe('NVDA');
  expect(container.querySelector('strong')?.textContent).toBe('strong');
  expect(container.querySelector('code')?.textContent).toBe('RSI');
  expect(container.querySelectorAll('li')).toHaveLength(2);
  const link = screen.getByRole('link', { name: 'docs' });
  expect(link).toHaveAttribute('href', 'https://x.io');
});

it('renders plain paragraphs', () => {
  const { container } = render(<Markdown text={'just text'} />);
  expect(container.querySelector('p')?.textContent).toBe('just text');
});

it('neutralizes non-http link schemes', () => {
  render(<Markdown text={'click [here](javascript:alert(1))'} />);
  const link = screen.getByRole('link', { name: 'here' });
  expect(link).toHaveAttribute('href', '#');
});
