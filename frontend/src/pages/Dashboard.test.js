import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';
import Dashboard, { displayName, recentOutfits, recentlyAdded } from './Dashboard';
import { clearProfileCache } from '../components/PageHeader';

jest.mock('axios');

const NOW = Date.now();
const ITEMS = [
  { _id: 'a', category: 'Saree', group: 'Sarees', display_name: 'Red Saree', image_path: 'https://x/a.jpg',
    created_at: new Date(NOW - 3600e3).toUTCString() },
  { _id: 'b', category: 'Heels', group: 'Shoes', display_name: 'Gold Heels', image_path: 'https://x/b.jpg',
    created_at: new Date(NOW - 30 * 86400e3).toUTCString() },
];

function mock({ name = 'Meera', gender = 'Female', history = [], items = ITEMS } = {}) {
  axios.get.mockImplementation((url) => {
    if (url.endsWith('/api/user/profile')) return Promise.resolve({ data: { profile: { name, email: 'someone@example.com', gender } } });
    if (url.endsWith('/api/wardrobe')) return Promise.resolve({ data: { items } });
    if (url.endsWith('/api/outfits/history')) return Promise.resolve({ data: { history } });
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  clearProfileCache();
  localStorage.clear();
  localStorage.setItem('token', 't');
});

test('greets the signed-in user by the name on their account', async () => {
  mock({ name: 'Meera Rao' });
  render(<MemoryRouter><Dashboard /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Meera'));
  expect(await screen.findByText('2 items')).toBeInTheDocument();
});

test('a different account gets its own name - nothing is hard-coded', async () => {
  mock({ name: 'Arjun', gender: 'Male', items: [] });
  localStorage.setItem('name', 'Ganga'); // stale browser data must not matter
  const { container } = render(<MemoryRouter><Dashboard /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Arjun'));
  expect(container.textContent).not.toMatch(/ganga|ram\b|dhanya/i);
  expect(screen.getByText('Men')).toBeInTheDocument();
});

test('does not repeat the sidebar as cards or list wardrobe categories', async () => {
  mock();
  const { container } = render(<MemoryRouter><Dashboard /></MemoryRouter>);
  await screen.findByText('2 items');
  // links inside the Home content (the sidebar is the app's navigation)
  const hrefs = [...container.querySelectorAll('.hm a')].map((a) => a.getAttribute('href'));
  for (const route of ['/wardrobe', '/trip', '/tryon', '/similar']) expect(hrefs).not.toContain(route);
  expect(hrefs.filter((h) => h === '/recommend')).toHaveLength(1); // the one main action
  const home = container.querySelector('.hm');
  for (const cat of ['Tops', 'Bottoms', 'Dresses', 'Sarees', 'Outerwear', 'Accessories']) {
    expect(home.textContent).not.toContain(cat);
  }
});

test('no history -> clean empty state, no invented outfits', async () => {
  mock();
  render(<MemoryRouter><Dashboard /></MemoryRouter>);
  expect(await screen.findByText(/your wardrobe story starts here/i)).toBeInTheDocument();
});

test('shows real wear history and recently added pieces when they exist', async () => {
  mock({ history: [{ outfit_key: 'a|b', item_ids: ['b', 'a'], occasion: 'wedding', worn_at: new Date(NOW).toISOString() }] });
  render(<MemoryRouter><Dashboard /></MemoryRouter>);
  expect(await screen.findByText('Wedding')).toBeInTheDocument();
  expect(screen.getByAltText('Red Saree')).toBeInTheDocument();         // worn outfit cover
  expect(screen.getByText('Red Saree', { selector: 'strong' })).toBeInTheDocument(); // recently added
});

test('helpers', () => {
  expect(displayName({ name: '', email: 'riya@gmail.com' })).toBe('riya');
  expect(displayName(null)).toBe('there');
  const history = [{ outfit_key: 'a|b', item_ids: ['b', 'a'], worn_at: 'x' },
                   { outfit_key: 'gone', item_ids: ['deleted'], worn_at: 'y' }];
  expect(recentOutfits(history, ITEMS).map((o) => o.cover._id)).toEqual(['a']);
  expect(recentlyAdded(ITEMS).map((i) => i._id)).toEqual(['a', 'b']);
  expect(recentlyAdded([{ _id: 'z' }])).toEqual([]);
});
