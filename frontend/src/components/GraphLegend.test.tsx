import { expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { GraphLegend } from './GraphLegend';

it('renders the colour keys and collapses', () => {
  render(<GraphLegend />);
  expect(screen.getByText('buy')).toBeInTheDocument();
  expect(screen.getByText('imported')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /legend/i }));
  expect(screen.queryByText('buy')).not.toBeInTheDocument();
});
