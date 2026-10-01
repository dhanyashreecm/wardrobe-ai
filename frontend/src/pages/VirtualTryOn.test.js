import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';
import VirtualTryOn, { applySelection } from './VirtualTryOn';

jest.mock('axios');

const CAPABILITY = {
  success: true,
  available: true,
  message: null,
  missing_configuration: [],
  has_photo: false,
  photo_url: null,
  max_upload_mb: 8,
  max_garments: 3,
  supports_full_outfit: true,
  photo_guidance: ['Stand facing the camera.'],
};

const ok = { supported: true, shown_beside: false, reason: '' };
const GARMENTS = [
  { _id: 'shirt1', category: 'Shirt', display_name: 'White Shirt', image_path: 'https://res.cloudinary.com/x/s.jpg', tryon: { ...ok, slot: 'top' } },
  { _id: 'jeans1', category: 'Jeans', display_name: 'Blue Jeans', image_path: 'https://res.cloudinary.com/x/j.jpg', tryon: { ...ok, slot: 'bottom' } },
  { _id: 'dress1', category: 'Dress', display_name: 'Red Dress', image_path: 'https://res.cloudinary.com/x/d.jpg', tryon: { ...ok, slot: 'one_piece' } },
  { _id: 'saree1', category: 'Saree', display_name: 'Silk Saree', image_path: 'https://res.cloudinary.com/x/sa.jpg',
    tryon: { supported: false, slot: null, shown_beside: false, reason: 'A saree is a draped garment.' } },
];

function mockApi({ capability = CAPABILITY, garments = GARMENTS, status = [], results = [] } = {}) {
  const statuses = [...status];
  axios.get.mockImplementation((url) => {
    if (url.endsWith('/api/tryon/capability')) return Promise.resolve({ data: capability });
    if (url.endsWith('/api/tryon/garments')) return Promise.resolve({ data: { success: true, items: garments } });
    if (url.endsWith('/api/tryon/results')) return Promise.resolve({ data: { success: true, results } });
    if (url.includes('/api/tryon/status/')) {
      const next = statuses.length > 1 ? statuses.shift() : statuses[0];
      return next instanceof Error ? Promise.reject(next) : Promise.resolve({ data: { success: true, job: next } });
    }
    return Promise.resolve({ data: { profile: { name: 'Test', gender: 'female' } } });
  });
}

function renderPage(state) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/tryon', state }]}>
      <VirtualTryOn />
    </MemoryRouter>
  );
}

const tryOnButton = () => screen.getByRole('button', { name: /^try on$|creating/i });

beforeAll(() => {
  global.URL.createObjectURL = jest.fn(() => 'blob:preview');
  global.URL.revokeObjectURL = jest.fn();
});

beforeEach(() => {
  jest.clearAllMocks();
  jest.useRealTimers();
  localStorage.setItem('token', 'test-token');
});

test('renders the Virtual Try-On page with its four steps', async () => {
  mockApi();
  renderPage();
  expect(await screen.findByRole('heading', { name: /your photo/i })).toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 1, name: /virtual try-on/i })).toBeInTheDocument();
  expect(screen.getByText('See how your wardrobe looks on you.')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /choose an item/i })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /try it on/i })).toBeInTheDocument();
});

test('loads garments from the authenticated try-on endpoint only', async () => {
  mockApi();
  renderPage();
  expect(await screen.findByText('White Shirt')).toBeInTheDocument();
  const call = axios.get.mock.calls.find(([url]) => url.endsWith('/api/tryon/garments'));
  expect(call[1].headers.Authorization).toBe('Bearer test-token');
  // never asks for a user id or anyone else's wardrobe
  expect(call[0]).not.toMatch(/user|email/i);
  expect(axios.get.mock.calls.some(([url]) => /\/api\/wardrobe\b/.test(url))).toBe(false);
});

test('shows only the items the backend returned for this user', async () => {
  mockApi({ garments: [GARMENTS[0]] });
  renderPage();
  expect(await screen.findByText('White Shirt')).toBeInTheDocument();
  expect(screen.queryByText('Blue Jeans')).not.toBeInTheDocument();
  expect(screen.queryByText('Red Dress')).not.toBeInTheDocument();
});

test('unsupported garments are listed with their reason and are not selectable', async () => {
  mockApi();
  renderPage();
  await screen.findByText('White Shirt');
  expect(screen.getByText(/not available for try-on \(1\)/i)).toBeInTheDocument();
  expect(screen.getByText('A saree is a draped garment.')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /silk saree/i })).not.toBeInTheDocument();
});

test('upload control sends the photo and shows a preview', async () => {
  mockApi();
  axios.post.mockResolvedValue({ data: { success: true, photo_url: 'https://res.cloudinary.com/x/me.jpg' } });
  renderPage();
  await screen.findByText('Upload Photo');
  const input = screen.getByTestId('photo-input');
  const file = new File(['png'], 'me.png', { type: 'image/png' });
  await act(async () => { fireEvent.change(input, { target: { files: [file] } }); });
  const preview = await screen.findByTestId('photo-preview');
  await waitFor(() => expect(preview).toHaveAttribute('src', 'https://res.cloudinary.com/x/me.jpg'));
  const [url, body] = axios.post.mock.calls[0];
  expect(url).toMatch(/\/api\/tryon\/photo$/);
  expect(body.get('image')).toBe(file);
  expect(screen.getByRole('button', { name: 'Replace' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument();
});

test('a non-image file is refused before upload', async () => {
  mockApi();
  renderPage();
  await screen.findByText('Upload Photo');
  const file = new File(['%PDF'], 'doc.pdf', { type: 'application/pdf' });
  fireEvent.change(screen.getByTestId('photo-input'), { target: { files: [file] } });
  expect(await screen.findByText(/please choose a photo/i)).toBeInTheDocument();
  expect(axios.post).not.toHaveBeenCalled();
});

test('photo problems from the server are shown', async () => {
  mockApi();
  axios.post.mockRejectedValue({ response: { status: 400, data: { message: 'x', problems: ['The photo is too small.'] } } });
  renderPage();
  await screen.findByText('Upload Photo');
  await act(async () => {
    fireEvent.change(screen.getByTestId('photo-input'), { target: { files: [new File(['p'], 'a.png', { type: 'image/png' })] } });
  });
  expect(await screen.findByText('The photo is too small.')).toBeInTheDocument();
});

test('Try On is disabled until a photo and a garment are chosen', async () => {
  mockApi();
  renderPage();
  await screen.findByText('White Shirt');
  expect(tryOnButton()).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: /white shirt/i }));
  expect(tryOnButton()).toBeDisabled(); // still no photo
});

test('user can select a garment and it is enabled once a photo exists', async () => {
  mockApi({ capability: { ...CAPABILITY, has_photo: true, photo_url: 'https://res.cloudinary.com/x/me.jpg' } });
  renderPage();
  const shirt = await screen.findByRole('button', { name: /white shirt/i });
  fireEvent.click(shirt);
  expect(shirt).toHaveAttribute('aria-pressed', 'true');
  expect(tryOnButton()).toBeEnabled();
});

test('shows the loading state, then the generated result', async () => {
  mockApi({
    capability: { ...CAPABILITY, photo_url: 'https://res.cloudinary.com/x/me.jpg' },
    status: [
      { job_id: 'j1', status: 'running', step: 1, total_steps: 1 },
      { job_id: 'j1', status: 'done', image_url: 'https://res.cloudinary.com/x/result.png', worn: [], not_applied: [] },
    ],
  });
  axios.post.mockResolvedValue({ data: { success: true, job_id: 'j1', total_steps: 1, not_applied: [] } });
  jest.useFakeTimers();
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });

  expect(axios.post).toHaveBeenCalledWith(
    expect.stringMatching(/\/api\/tryon\/generate$/),
    expect.objectContaining({ item_ids: ['shirt1'] }),
    expect.anything()
  );
  expect(screen.getByText('Creating your virtual look...')).toBeInTheDocument();

  await act(async () => { jest.advanceTimersByTime(2100); });
  await act(async () => { jest.advanceTimersByTime(3100); });

  const result = await screen.findByTestId('tryon-result');
  expect(result).toHaveTextContent('Your Virtual Look');
  expect(screen.getByAltText('Your virtual look')).toHaveAttribute('src', 'https://res.cloudinary.com/x/result.png');
  expect(screen.queryByText('Creating your virtual look...')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Try Another' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save Result' })).toBeInTheDocument();
});

test('a failed generation shows an understandable error and stops polling', async () => {
  mockApi({
    capability: { ...CAPABILITY, photo_url: 'https://res.cloudinary.com/x/me.jpg' },
    status: [{ job_id: 'j2', status: 'failed', error: 'The try-on took too long and was stopped.' }],
  });
  axios.post.mockResolvedValue({ data: { success: true, job_id: 'j2', total_steps: 1, not_applied: [] } });
  jest.useFakeTimers();
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });
  await act(async () => { jest.advanceTimersByTime(2100); });
  expect(await screen.findByRole('alert')).toHaveTextContent('The try-on took too long and was stopped.');
  const polls = axios.get.mock.calls.filter(([url]) => url.includes('/status/')).length;
  await act(async () => { jest.advanceTimersByTime(20000); });
  expect(axios.get.mock.calls.filter(([url]) => url.includes('/status/')).length).toBe(polls);
});

test('unsupported garment rejected by the server shows its message', async () => {
  mockApi({ capability: { ...CAPABILITY, photo_url: 'https://res.cloudinary.com/x/me.jpg' } });
  axios.post.mockRejectedValue({ response: { status: 400, data: { code: 'unsupported_garment', message: 'Only one top can be tried on at a time.' } } });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });
  expect(await screen.findByRole('alert')).toHaveTextContent('Only one top can be tried on at a time.');
});

test('network failure shows a friendly message', async () => {
  mockApi({ capability: { ...CAPABILITY, photo_url: 'https://res.cloudinary.com/x/me.jpg' } });
  axios.post.mockRejectedValue(new Error('Network Error'));
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });
  expect(await screen.findByRole('alert')).toHaveTextContent(/can't reach the server/i);
});

test('not-configured state says so and offers no try-on form', async () => {
  mockApi({ capability: { ...CAPABILITY, available: false, message: 'Virtual Try-On is not configured yet.',
    missing_configuration: ['TRYON_SPACE_ID', 'HUGGINGFACE_API_TOKEN'] } });
  renderPage();
  const panel = await screen.findByTestId('tryon-not-configured');
  expect(panel).toHaveTextContent('Virtual Try-On is not configured yet.');
  expect(panel).toHaveTextContent('TRYON_SPACE_ID');
  expect(screen.queryByRole('button', { name: /^try on$/i })).not.toBeInTheDocument();
});

test('no raw provider or API details appear in the UI', async () => {
  mockApi({
    capability: { ...CAPABILITY, photo_url: 'https://res.cloudinary.com/x/me.jpg' },
    results: [{ job_id: 'old', status: 'done', image_url: 'https://res.cloudinary.com/x/old.png', worn: [{ category: 'Shirt' }],
      label: '', model: 'fashn-vton-1.5', provider: 'huggingface_space' }],
    status: [{ job_id: 'j3', status: 'done', image_url: 'https://res.cloudinary.com/x/r.png',
      model: 'fashn-vton-1.5', model_license: 'Apache-2.0', provider: 'huggingface_space' }],
  });
  axios.post.mockResolvedValue({ data: { success: true, job_id: 'j3', total_steps: 1, not_applied: [] } });
  jest.useFakeTimers();
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });
  await act(async () => { jest.advanceTimersByTime(2100); });
  await screen.findByTestId('tryon-result');
  const text = document.body.textContent.toLowerCase();
  for (const word of ['fashn', 'hugging', 'apache', 'gradio', 'api key', 'token', 'traceback']) {
    expect(text).not.toContain(word);
  }
});

test('a garment handed over from the wardrobe is pre-selected', async () => {
  mockApi();
  renderPage({ itemIds: ['jeans1'], source: 'wardrobe', label: 'Blue Jeans' });
  await screen.findByText('White Shirt');
  await waitFor(() =>
    expect(screen.getByRole('button', { name: /blue jeans/i })).toHaveAttribute('aria-pressed', 'true'));
});

test('a recommended outfit pre-selects what can be worn and explains what cannot', async () => {
  mockApi();
  renderPage({ itemIds: ['shirt1', 'jeans1', 'saree1'], source: 'recommendation', label: 'Party look' });
  await screen.findByText('White Shirt');
  await waitFor(() =>
    expect(screen.getByRole('button', { name: /white shirt/i })).toHaveAttribute('aria-pressed', 'true'));
  expect(screen.getByRole('button', { name: /blue jeans/i })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByText(/Silk Saree: A saree is a draped garment\./)).toBeInTheDocument();
});

test('selection rules: one per slot, a dress replaces top and bottom, single-garment providers get one', () => {
  expect(applySelection(['shirt1'], GARMENTS[1], GARMENTS, 3)).toEqual(['shirt1', 'jeans1']);
  expect(applySelection(['shirt1', 'jeans1'], GARMENTS[2], GARMENTS, 3)).toEqual(['dress1']);
  expect(applySelection(['dress1'], GARMENTS[0], GARMENTS, 3)).toEqual(['shirt1']);
  expect(applySelection(['shirt1'], GARMENTS[1], GARMENTS, 1)).toEqual(['jeans1']);
  expect(applySelection(['shirt1'], GARMENTS[0], GARMENTS, 3)).toEqual([]);
});

// ---------------- provider status (orchestrator) ----------------

const READY_MSG = 'Virtual Try-On is ready.';
const FALLBACK_MSG = 'Primary try-on service is temporarily unavailable. Using another available try-on service.';
const NONE_MSG = 'Free Virtual Try-On is temporarily unavailable. Your wardrobe and all other AI Wardrobe features are still available. Try again when a provider becomes available.';
const WITH_PHOTO = { ...CAPABILITY, photo_url: 'https://res.cloudinary.com/x/me.jpg' };
const READY = { ...WITH_PHOTO, status: 'ready', message: READY_MSG, reason: null };
const QUOTA = { ...WITH_PHOTO, available: false, status: 'unavailable', message: NONE_MSG,
  reason: "Today's free try-on allowance has been used up (it resets within 24 hours)." };
const FALLBACK = { ...WITH_PHOTO, status: 'fallback', message: FALLBACK_MSG, reason: null };

const capabilityCalls = () => axios.get.mock.calls.filter(([url]) => url.endsWith('/api/tryon/capability')).length;

test('provider ready: shows the ready message and Try On works', async () => {
  mockApi({ capability: READY });
  renderPage();
  expect(await screen.findByTestId('tryon-status')).toHaveTextContent(READY_MSG);
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  expect(tryOnButton()).toBeEnabled();
});

test('quota exhausted: page stays usable, explains why, and Try On is paused', async () => {
  mockApi({ capability: QUOTA });
  renderPage();
  const banner = await screen.findByTestId('tryon-status');
  expect(banner).toHaveTextContent(NONE_MSG);
  expect(banner).toHaveTextContent(/allowance has been used up/);
  expect(screen.queryByTestId('tryon-not-configured')).not.toBeInTheDocument();
  // wardrobe and photo steps are still there
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  expect(tryOnButton()).toBeDisabled();
  expect(axios.post).not.toHaveBeenCalled();
  // "Check again" only re-reads the status - it never submits a try-on
  const before = capabilityCalls();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /check again/i })); });
  expect(capabilityCalls()).toBe(before + 1);
  expect(axios.post).not.toHaveBeenCalled();
});

test('fallback active: explains the switch and still allows a try-on', async () => {
  mockApi({ capability: FALLBACK });
  renderPage();
  expect(await screen.findByTestId('tryon-status')).toHaveTextContent(FALLBACK_MSG);
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  expect(tryOnButton()).toBeEnabled();
});

test('all providers unavailable when starting: clear message, Retry submits once only when a provider is back', async () => {
  mockApi({ capability: READY });
  axios.post.mockRejectedValueOnce({ response: { status: 503, data: { code: 'unavailable', message: NONE_MSG } } });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  mockApi({ capability: QUOTA });
  await act(async () => { fireEvent.click(tryOnButton()); });
  const alerts = await screen.findAllByRole('alert');
  expect(alerts.some((a) => a.textContent.includes(NONE_MSG))).toBe(true);
  expect(axios.post).toHaveBeenCalledTimes(1);

  // Still unavailable: Retry checks, but submits nothing.
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /^retry$/i })); });
  expect(axios.post).toHaveBeenCalledTimes(1);

  // A provider is back: Retry submits exactly one new try-on.
  mockApi({ capability: READY, status: [{ job_id: 'j9', status: 'running' }] });
  axios.post.mockResolvedValueOnce({ data: { success: true, job_id: 'j9', total_steps: 1, not_applied: [] } });
  const retryButton = screen.getByRole('button', { name: /^retry$/i });
  await act(async () => { fireEvent.click(retryButton); fireEvent.click(retryButton); });
  await waitFor(() => expect(axios.post).toHaveBeenCalledTimes(2));
});

test('a job that failed because of the provider offers Retry; an input problem does not', async () => {
  mockApi({ capability: READY, status: [{ job_id: 'j5', status: 'failed', error: NONE_MSG, error_code: 'QUOTA_EXHAUSTED' }] });
  axios.post.mockResolvedValue({ data: { success: true, job_id: 'j5', total_steps: 1, not_applied: [] } });
  jest.useFakeTimers();
  const first = renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });
  await act(async () => { jest.advanceTimersByTime(2100); });
  expect(await screen.findByRole('button', { name: /^retry$/i })).toBeInTheDocument();
  first.unmount();

  mockApi({ capability: READY, status: [{ job_id: 'j6', status: 'failed', error: 'We could not find a person in that photo.', error_code: 'UNSUPPORTED_INPUT' }] });
  axios.post.mockResolvedValue({ data: { success: true, job_id: 'j6', total_steps: 1, not_applied: [] } });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });
  await act(async () => { jest.advanceTimersByTime(2100); });
  await screen.findByText(/could not find a person/);
  expect(screen.queryByRole('button', { name: /^retry$/i })).not.toBeInTheDocument();
});

test('a result made by the fallback service is real and says so generically', async () => {
  mockApi({
    capability: READY,
    status: [{ job_id: 'j7', status: 'done', image_url: 'https://res.cloudinary.com/x/fb.png', worn: [], not_applied: [],
      notice: 'Created with a backup try-on service because the main one was unavailable.' }],
  });
  axios.post.mockResolvedValue({ data: { success: true, job_id: 'j7', total_steps: 1, not_applied: [] } });
  jest.useFakeTimers();
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });
  await act(async () => { jest.advanceTimersByTime(2100); });
  await screen.findByTestId('tryon-result');
  expect(screen.getByAltText('Your virtual look')).toHaveAttribute('src', 'https://res.cloudinary.com/x/fb.png');
  expect(screen.getByTestId('tryon-notice')).toHaveTextContent(/backup try-on service/);
});

test('Try Another clears the result and the selection', async () => {
  mockApi({
    capability: READY,
    status: [{ job_id: 'j8', status: 'done', image_url: 'https://res.cloudinary.com/x/r8.png', worn: [], not_applied: [] }],
  });
  axios.post.mockResolvedValue({ data: { success: true, job_id: 'j8', total_steps: 1, not_applied: [] } });
  jest.useFakeTimers();
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });
  await act(async () => { jest.advanceTimersByTime(2100); });
  await screen.findByTestId('tryon-result');
  fireEvent.click(screen.getByRole('button', { name: 'Try Another' }));
  expect(screen.queryByTestId('tryon-result')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /white shirt/i })).toHaveAttribute('aria-pressed', 'false');
  expect(tryOnButton()).toBeDisabled();
});

test('recent try-ons are listed and can be reopened, even while providers are unavailable', async () => {
  mockApi({
    capability: QUOTA,
    results: [{ job_id: 'r1', status: 'done', image_url: 'https://res.cloudinary.com/x/old.png', label: 'Office look', worn: [] }],
  });
  renderPage();
  expect(await screen.findByText('Recent Try-Ons')).toBeInTheDocument();
  fireEvent.click(screen.getByAltText('Office look'));
  expect(await screen.findByTestId('tryon-result')).toBeInTheDocument();
});

// ---------------------------------------------------------------
// The daily allowance, as the page reports it. What is on screen has
// to be exactly what the backend said - a counter that guesses is
// worse than no counter.
// ---------------------------------------------------------------

const withUsage = (extra) => ({
  ...CAPABILITY,
  photo_url: 'https://res.cloudinary.com/x/me.jpg',
  has_photo: true,
  usage: {
    used: 3, limit: 10, remaining: 7, successful: 3, in_progress: 0,
    day: '2026-10-01', resets_at: '2026-10-01T18:30:00Z',
    ...extra,
  },
});

test('the counter shows successful generations out of the daily limit', async () => {
  mockApi({ capability: withUsage() });
  renderPage();
  const line = await screen.findByText(/try-ons created today/i);
  expect(line).toHaveTextContent('3/10');
  expect(line).toHaveTextContent('7 remaining');
});

test('a generation still running is shown as in progress, not as an image', async () => {
  mockApi({ capability: withUsage({ used: 4, remaining: 6, successful: 3, in_progress: 1 }) });
  renderPage();
  const line = await screen.findByText(/try-ons created today/i);
  // Three images exist; the fourth is not one yet.
  expect(line).toHaveTextContent('3/10');
  expect(line).toHaveTextContent('1 in progress');
});

test('using the whole allowance disables Try On and says so', async () => {
  mockApi({ capability: withUsage({ used: 10, remaining: 0, successful: 10 }) });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  expect(await screen.findByText(/created all 10 of today's virtual try-ons/i)).toBeInTheDocument();
  expect(tryOnButton()).toBeDisabled();
});

test('a failure that cost nothing says so instead of implying the allowance is gone', async () => {
  mockApi({
    capability: withUsage(),
    status: [{
      job_id: 'jf', status: 'failed', error: 'The try-on service is starting up.',
      error_code: 'PROVIDER_SLEEPING', attempt_charged: false, outcome: 'confirmed',
    }],
  });
  axios.post.mockResolvedValue({ data: { success: true, job_id: 'jf', total_steps: 1, not_applied: [] } });
  jest.useFakeTimers();
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });
  await act(async () => { jest.advanceTimersByTime(2100); });
  expect(await screen.findByText(/didn't use one of your daily attempts/i)).toBeInTheDocument();
});

test('an unconfirmed outcome says the attempt is on hold, not spent', async () => {
  mockApi({
    capability: withUsage(),
    status: [{
      job_id: 'ju', status: 'failed', error: 'The try-on service was too slow to respond.',
      error_code: 'TIMEOUT', attempt_charged: true, outcome: 'uncertain',
    }],
  });
  axios.post.mockResolvedValue({ data: { success: true, job_id: 'ju', total_steps: 1, not_applied: [] } });
  jest.useFakeTimers();
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });
  await act(async () => { jest.advanceTimersByTime(2100); });
  expect(await screen.findByText(/on hold/i)).toBeInTheDocument();
});

test('a repeated submission reuses one request id so it cannot be charged twice', async () => {
  mockApi({
    capability: withUsage(),
    status: [{ job_id: 'j1', status: 'running' }],
  });
  axios.post.mockResolvedValue({ data: { success: true, job_id: 'j1', total_steps: 1, not_applied: [] } });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /white shirt/i }));
  await act(async () => { fireEvent.click(tryOnButton()); });
  const body = axios.post.mock.calls[0][1];
  expect(typeof body.request_id).toBe('string');
  expect(body.request_id.length).toBeGreaterThan(0);
  // The button is disabled while it runs, so a second click sends nothing.
  expect(tryOnButton()).toBeDisabled();
  await act(async () => { fireEvent.click(tryOnButton()); });
  expect(axios.post).toHaveBeenCalledTimes(1);
});
