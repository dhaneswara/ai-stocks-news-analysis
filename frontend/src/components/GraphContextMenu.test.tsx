import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { GraphContextMenu } from './GraphContextMenu';

it('renders items, fires onClick then onClose', () => {
  const onClose = vi.fn(); const onClick = vi.fn();
  render(<GraphContextMenu x={10} y={20} onClose={onClose} items={[{ label: 'Delete node', danger: true, onClick }]} />);
  fireEvent.click(screen.getByRole('menuitem', { name: /delete node/i }));
  expect(onClick).toHaveBeenCalled();
  expect(onClose).toHaveBeenCalled();
});

it('closes on Escape', () => {
  const onClose = vi.fn();
  render(<GraphContextMenu x={0} y={0} onClose={onClose} items={[{ label: 'X', onClick: vi.fn() }]} />);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(onClose).toHaveBeenCalled();
});

it('closes on outside mousedown', () => {
  const onClose = vi.fn();
  render(<GraphContextMenu x={0} y={0} onClose={onClose} items={[{ label: 'X', onClick: vi.fn() }]} />);
  fireEvent.mouseDown(document.body);
  expect(onClose).toHaveBeenCalled();
});
