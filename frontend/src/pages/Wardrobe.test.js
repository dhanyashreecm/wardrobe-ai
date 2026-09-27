import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';
import Wardrobe from './Wardrobe';

jest.mock('axios');
jest.mock('react-easy-crop', () => () => null);

const ITEMS = [
  { _id: '1', category: 'Shirt', color: 'white', display_name: 'White Shirt', group: 'Tops',
    style_label: 'Smart', image_path: 'https://res.cloudinary.com/x/1.jpg', suitable_occasions: ['college'] },
];

function mockGets({ auto = false, items = ITEMS } = {}) {
  axios.get.mockImplementation((url) => {
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
  fireEvent.change(screen.getByDisplayValue(/choose a category/i), { target: { value: 'Denims' } });
  fireEvent.change(screen.getByPlaceholderText('e.g. black, navy, dusty pink'), { target: { value: 'blue' } });
  fireEvent.click(save);

  await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1));
  const [url, form, config] = axios.post.mock.calls[0];
  expect(url).toMatch(/\/api\/wardrobe\/add$/);
  expect(form.get('image')).toBeInstanceOf(File);
  expect(form.get('category')).toBe('Denims');
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
