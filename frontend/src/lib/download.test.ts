import { afterEach, expect, it, vi } from 'vitest';
import { downloadText } from './download';

const origCreate = URL.createObjectURL;
const origRevoke = URL.revokeObjectURL;
afterEach(() => {
  URL.createObjectURL = origCreate;
  URL.revokeObjectURL = origRevoke;
  vi.restoreAllMocks();
});

it('creates an object URL, clicks an anchor with the filename, and revokes the URL', () => {
  URL.createObjectURL = vi.fn(() => 'blob:abc');
  URL.revokeObjectURL = vi.fn();
  let downloadAttr = '';
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    downloadAttr = this.download;
  });

  downloadText('graph.json', '{"a":1}');

  expect(URL.createObjectURL).toHaveBeenCalledOnce();
  expect(click).toHaveBeenCalledOnce();
  expect(downloadAttr).toBe('graph.json');
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:abc');
});
