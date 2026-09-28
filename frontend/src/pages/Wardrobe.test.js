import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';
import Wardrobe from './Wardrobe';
import { clearCategoryCache } from '../lib/categories';
import REAL_CATEGORIES from '../__fixtures__/categories.json';

jest.mock('axios');
jest.mock('react-easy-crop', () => () => null);

const ITEMS = [
  { _id: '1', category: 'Shirt', color: 'white', display_name: 'White Shirt', group: 'Tops',
    style_label: 'Smart', image_path: 'https://res.cloudinary.com/x/1.jpg', suitable_occasions: ['college'] },
];

const SECTIONS = {
  female: [
    { name: 'Tops', categories: [{ value: 'Shirt', label: 'Shirt', flags: [] }, { value: 'Crop Top', label: 'Crop Top', flags: [] }] },
    { name: 'Bottoms', categories: [{ value: 'Jeans', label: 'Jeans / Denim', flags: [] }] },
    { name: 'Traditional', categories: [{ value: 'Saree', label: 'Saree', flags: ['styling'] }] },
  ],
  male: [
    { name: 'Tops', categories: [{ value: 'Shirt', label: 'Shirt', flags: [] }, { value: 'Sports Jersey', label: 'Sports Jersey', flags: [] }] },
    { name: 'Bottoms', categories: [{ value: 'Jeans', label: 'Jeans / Denim', flags: [] }, { value: 'Trousers', label: 'Trousers / Pants', flags: [] }, { value: 'Track Pants', label: 'Track Pants', flags: [] }] },
    { name: 'Traditional', categories: [{ value: 'Sherwani', label: 'Sherwani', flags: [] }] },
  ],
};

function mockGets({ auto = false, items = ITEMS, gender = 'female' } = {}) {
  axios.get.mockImplementation((url) => {
    if (url.endsWith('/api/wardrobe/categories')) return Promise.resolve({ data: { success: true, gender, sections: SECTIONS[gender] } });
    if (url.endsWith('/api/wardrobe')) return Promise.resolve({ data: { success: true, items } });
    if (url.endsWith('/api/wardrobe/capabilities')) return Promise.resolve({ data: { auto_category: auto } });
    return Promise.resolve({ data: { profile: { name: 'Test' } } });
  });
}

async function openToDetails() {
  render(<MemoryRouter><Wardrobe /></MemoryRouter>);
  await screen.findByText('White Shirt');
  fireEvent.click(screen.getByRole('button', { name: /add new item/i }));
  const input = document.querySelector('input[type="file"]');
  const file = new File(['png'], 'photo.png', { type: 'image/png' });
  fireEvent.change(input, { target: { files: [file] } });
  fireEvent.click(await screen.findByRole('button', { name: /skip crop/i }));
  return screen.findByRole('button', { name: /add to wardrobe/i });
}

beforeEach(() => {
  jest.clearAllMocks();
  clearCategoryCache();
  localStorage.setItem('token', 'test-token');
  localStorage.setItem('gender', 'Female');
});

test('loads the logged-in user wardrobe', async () => {
  mockGets();
  render(<MemoryRouter><Wardrobe /></MemoryRouter>);
  expect(await screen.findByText('White Shirt')).toBeInTheDocument();
  const call = axios.get.mock.calls.find(([url]) => url.endsWith('/api/wardrobe'));
  expect(call[1].headers.Authorization).toBe('Bearer test-token');
});

test('uploads image + details, shows success and refreshes the wardrobe', async () => {
  mockGets();
  axios.post.mockResolvedValue({ data: { success: true, item_id: 'new', category: 'Denims', color: 'blue', image: 'https://res.cloudinary.com/x/new.jpg' } });
  const save = await openToDetails();
  fireEvent.change(screen.getByDisplayValue(/choose a category/i), { target: { value: 'Jeans' } });
  fireEvent.change(screen.getByPlaceholderText('e.g. black, navy, dusty pink'), { target: { value: 'blue' } });
  fireEvent.click(save);

  await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
  const [url, form, config] = axios.post.mock.calls[0];
  expect(url).toMatch(/\/api\/wardrobe\/add$/);
  expect(form.get('image')).toBeInstanceOf(File);
  expect(form.get('category')).toBe('Jeans');
  expect(form.get('category_explicit')).toBe('true');
  expect(form.get('color')).toBe('blue');
  expect(config.headers.Authorization).toBe('Bearer test-token');

  expect(await screen.findByText(/added to your wardrobe/i)).toBeInTheDocument();
  await waitFor(() => {
    const refreshes = axios.get.mock.calls.filter(([u]) => u.endsWith('/api/wardrobe'));
    expect(refreshes.length).toBeGreaterThanOrEqual(2);
  }, { timeout: 3000 });
});

test('shows the real backend error instead of "Upload failed."', async () => {
  mockGets();
  axios.post.mockRejectedValue({ response: { status: 502, data: { message: 'Upload failed: the image could not be stored in the cloud (Cloudinary).' } } });
  const save = await openToDetails();
  fireEvent.change(screen.getByDisplayValue(/choose a category/i), { target: { value: 'Shirt' } });
  fireEvent.click(save);
  expect(await screen.findByRole('alert')).toHaveTextContent(/could not be stored/);
});

test('backend down gives a helpful message', async () => {
  mockGets();
  axios.post.mockRejectedValue(new Error('Network Error'));
  const save = await openToDetails();
  fireEvent.change(screen.getByDisplayValue(/choose a category/i), { target: { value: 'Shirt' } });
  fireEvent.click(save);
  expect(await screen.findByRole('alert')).toHaveTextContent(/can't reach the server/);
});

test('cannot submit twice while uploading', async () => {
  mockGets();
  let resolve;
  axios.post.mockReturnValue(new Promise((r) => { resolve = r; }));
  const save = await openToDetails();
  fireEvent.change(screen.getByDisplayValue(/choose a category/i), { target: { value: 'Shirt' } });
  fireEvent.click(save);
  fireEvent.click(save);
  fireEvent.click(save);
  expect(axios.post).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/uploading/i)).toBeInTheDocument();
  resolve({ data: { success: true, category: 'Shirt' } });
});

test('asks for a category when automatic recognition is unavailable', async () => {
  mockGets({ auto: false });
  const save = await openToDetails();
  fireEvent.click(save);
  expect(await screen.findByRole('alert')).toHaveTextContent(/choose a category/i);
  expect(axios.post).not.toHaveBeenCalled();
});

test('offers AI recognition when the classifier is available', async () => {
  mockGets({ auto: true });
  let resolve;
  axios.post.mockReturnValue(new Promise((r) => { resolve = r; }));
  const save = await openToDetails();
  expect(screen.getByDisplayValue(/let ai recognise it/i)).toBeInTheDocument();
  fireEvent.click(save);
  await waitFor(() => expect(axios.post).toHaveBeenCalled());
  expect(axios.post.mock.calls[0][1].get('category_explicit')).toBe('false');
  expect(screen.getByText(/recognising your item/i)).toBeInTheDocument();
  resolve({ data: { success: true, category: 'Saree', color: 'pink' } });
});

test('a men\'s account is only offered men\'s categories (from the server, not the browser)', async () => {
  localStorage.setItem('gender', 'Female'); // stale browser value must not matter
  mockGets({ gender: 'male' });
  await openToDetails();
  const select = screen.getByDisplayValue(/choose a category/i);
  await waitFor(() => expect(select.querySelectorAll('option').length).toBeGreaterThan(1));
  const values = [...select.querySelectorAll('option')].map((o) => o.value);
  expect(values).toContain('Sherwani');
  expect(values).toContain('Sports Jersey');
  expect(values).not.toContain('Saree');
  expect(values).not.toContain('Crop Top');
});

test('a women\'s account is not offered men\'s-only categories', async () => {
  mockGets({ gender: 'female' });
  await openToDetails();
  const select = screen.getByDisplayValue(/choose a category/i);
  await waitFor(() => expect(select.querySelectorAll('option').length).toBeGreaterThan(1));
  const values = [...select.querySelectorAll('option')].map((o) => o.value);
  expect(values).toContain('Saree');
  expect(values).not.toContain('Sherwani');
});

test('when the AI can only narrow it down, the user picks the exact type', async () => {
  mockGets({ auto: true, gender: 'male' });
  axios.post.mockRejectedValueOnce({ response: { status: 422, data: {
    success: false, needs_category: true, message: 'It looks like trousers - please choose the exact type.',
    options: [{ value: 'Trousers', label: 'Trousers / Pants' }, { value: 'Track Pants', label: 'Track Pants' }],
    guess: 'Trousers' } } });
  const save = await openToDetails();
  fireEvent.click(save);
  expect(await screen.findByRole('alert')).toHaveTextContent(/choose the exact type/);
  fireEvent.click(screen.getByRole('button', { name: 'Track Pants' }));
  axios.post.mockResolvedValueOnce({ data: { success: true, category: 'Track Pants' } });
  fireEvent.click(save);
  await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
  const form = axios.post.mock.calls[1][1];
  expect(form.get('category')).toBe('Track Pants');
  expect(form.get('category_explicit')).toBe('true');
});

// Regression for the reported bug: the male Add Item dropdown showed Dress,
// Saree and other women's categories. Uses the REAL catalogue the backend
// serves (generated from backend/category_catalog.py).
function mockReal(gender) {
  axios.get.mockImplementation((url) => {
    if (url.endsWith('/api/wardrobe/categories')) return Promise.resolve({ data: { success: true, gender, sections: REAL_CATEGORIES[gender] } });
    if (url.endsWith('/api/wardrobe')) return Promise.resolve({ data: { success: true, items: ITEMS } });
    if (url.endsWith('/api/wardrobe/capabilities')) return Promise.resolve({ data: { auto_category: false } });
    return Promise.resolve({ data: { profile: { name: 'Test' } } });
  });
}

async function dropdownValues() {
  await openToDetails();
  const select = screen.getByDisplayValue(/choose a category/i);
  await waitFor(() => expect(select.querySelectorAll('option').length).toBeGreaterThan(10));
  return [...select.querySelectorAll('option')].map((o) => o.value);
}

test('REGRESSION: male Add Item category dropdown has no women\'s categories', async () => {
  localStorage.setItem('gender', 'Female'); // stale browser data must not matter
  mockReal('male');
  const values = await dropdownValues();
  for (const cat of ['Saree', 'Casual Saree', 'Wedding Saree', 'Lehenga', 'Salwar Suit', 'Kurta (Women)',
    'Anarkali', 'Dupatta', 'Skirt', 'Dress', 'Gown', 'Jumpsuit', 'Romper', 'Crop Top', 'Leggings', 'Blouse']) {
    expect(values).not.toContain(cat);
  }
  for (const cat of ['T-Shirt', 'Shirt', 'Casual Shirt', 'Formal Shirt', 'Polo Shirt', 'Jeans', 'Trousers',
    'Chinos', 'Kurta (Men)', 'Sherwani', 'Nehru Jacket', 'Dhoti Pants', 'Blazer', 'Sports Jersey', 'Track Pants',
    'Sneakers', 'Formal Shoes', 'Sports Shoes', 'Belt', 'Watch', 'Tie']) {
    expect(values).toContain(cat);
  }
});

test('REGRESSION: female dropdown has women\'s categories and no men\'s-only ones', async () => {
  mockReal('female');
  const values = await dropdownValues();
  for (const cat of ['Saree', 'Casual Saree', 'Wedding Saree', 'Lehenga', 'Salwar Suit', 'Crop Top', 'Skirt', 'Dress']) {
    expect(values).toContain(cat);
  }
  for (const cat of ['Sherwani', 'Kurta (Men)', 'Nehru Jacket', 'Dhoti Pants', 'Tie', 'Bow Tie', 'Mojaris (Men)']) {
    expect(values).not.toContain(cat);
  }
});

test('no gender on the account -> empty selector with a message, never every category', async () => {
  axios.get.mockImplementation((url) => {
    if (url.endsWith('/api/wardrobe/categories')) return Promise.reject({ response: { status: 409, data: { message: 'no gender' } } });
    if (url.endsWith('/api/wardrobe')) return Promise.resolve({ data: { success: true, items: ITEMS } });
    if (url.endsWith('/api/wardrobe/capabilities')) return Promise.resolve({ data: { auto_category: false } });
    return Promise.resolve({ data: { profile: {} } });
  });
  await openToDetails();
  const select = screen.getByDisplayValue(/choose a category/i);
  expect(select.querySelectorAll('option')).toHaveLength(1);
  expect(screen.getAllByText(/gender information is required/i).length).toBeGreaterThan(0);
});
