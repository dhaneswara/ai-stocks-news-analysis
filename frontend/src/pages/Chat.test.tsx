import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import Chat from './Chat';
import { ChatProvider } from '../state/chatState';
import * as client from '../api/client';

function renderChat() {
  return render(<ChatProvider><Chat /></ChatProvider>);
}

it('shows suggestions and sends a question', () => {
  const send = vi.spyOn(client, 'streamChat').mockImplementation(() => () => {});
  renderChat();
  // suggestion chips visible in the empty state
  expect(screen.getByText(/strongest opportunity/i)).toBeInTheDocument();

  const box = screen.getByPlaceholderText(/Ask about a stock/i);
  fireEvent.change(box, { target: { value: 'Is NVDA a buy?' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));

  expect(send).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Is NVDA a buy?')).toBeInTheDocument();
});
