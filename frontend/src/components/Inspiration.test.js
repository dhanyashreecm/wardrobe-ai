import { render, screen } from '@testing-library/react';
import axios from 'axios';
import StyleInspiration from './Inspiration';

jest.mock('axios');

beforeEach(() => { localStorage.setItem('token', 't'); jest.clearAllMocks(); });

test('shows the pictures the server chose for this account and occasion, without links', async () => {
  axios.get.mockResolvedValue({ data: { images: [
    { id: 'm1', caption: 'Black Shirt', url: 'https://res.cloudinary.com/x/m1.jpg' },
    { id: 'm2', caption: 'Navy Blazer', url: '/api/inspiration/image/m2' },
  ] } });
  const { container } = render(<StyleInspiration occasion="party" label="Party" />);
  expect(await screen.findByText('Party Inspiration')).toBeInTheDocument();
  expect(container.querySelectorAll('img')).toHaveLength(2);
  expect(container.querySelectorAll('a')).toHaveLength(0);
  const [url, config] = axios.get.mock.calls[0];
  expect(url).toMatch(/\/api\/inspiration$/);
  expect(config.params).toEqual({ occasion: 'party' });
});

test('nothing is shown when there are no pictures', async () => {
  axios.get.mockResolvedValue({ data: { images: [] } });
  const { container } = render(<StyleInspiration occasion="party" label="Party" />);
  await new Promise((r) => setTimeout(r, 0));
  expect(container.innerHTML).toBe('');
});
