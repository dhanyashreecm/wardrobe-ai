import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import axios from 'axios';
import SimilarSearch, { formatPrice } from './SimilarSearch';

jest.mock('axios');

const PHOTO = new File(['x'], 'kurta.jpg', { type: 'image/jpeg' });

const ANALYSIS = {
  category: 'kurta', colour: 'pink', pattern: '', sleeve: '', neckline: '', silhouette: '',
  fabric: '', audience: 'women', keywords: '', secondary_colours: [], sources: { category: 'photo', colour: 'photo' },
  uncertain: false,
};

function wardrobeResponse(status, results) {
  return {
    data: {
      success: true, wardrobe_results: results, dataset_results: [], indofashion_results: [],
      category_results: {}, wardrobe_status: status, analysis: ANALYSIS,
    },
  };
}

const PRODUCTS = [
  { id: 'p0', title: 'Pink Embroidered Kurta', url: 'https://www.ajio.com/p/1', platform: 'AJIO',
    image: 'https://img.example/1.jpg', price: 1499, price_text: '₹1,499', currency: 'INR',
    in_stock: true, match: 'exact', matched_attributes: ['type', 'colour'], score: 5,
    title_category: 'kurta', title_colours: ['pink'] },
  { id: 'p1', title: 'Pink Straight Kurta', url: 'https://www.myntra.com/k/2', platform: 'Myntra',
    image: 'https://img.example/2.jpg', price: 899, price_text: '₹899', currency: 'INR',
    in_stock: null, match: 'similar_style', matched_attributes: ['type'], score: 2,
    title_category: 'kurta', title_colours: ['pink'] },
  { id: 'p2', title: 'Blue Kurta', url: 'https://www.flipkart.com/k/3', platform: 'Flipkart',
    image: '', price: null, price_text: null, currency: null,
    in_stock: false, match: 'same_category', matched_attributes: ['type'], score: 1,
    title_category: 'kurta', title_colours: ['blue'] },
];

const LINKS = [
  { platform: 'Myntra', url: 'https://www.myntra.com/pink-kurta?rawQuery=pink+kurta' },
  { platform: 'AJIO', url: 'https://www.ajio.com/search/?text=pink+kurta' },
];

function shopResponse(overrides = {}) {
  return { data: { success: true, status: 'exact_found', message: '', products: PRODUCTS,
    links: LINKS, query: 'pink kurta women', analysis: ANALYSIS, cached: false, ...overrides } };
}

let shopReply;
let wardrobeReply;

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  localStorage.setItem('token', 't');
  global.URL.createObjectURL = jest.fn(() => 'blob:preview');
  global.URL.revokeObjectURL = jest.fn();
  shopReply = () => Promise.resolve(shopResponse());
  wardrobeReply = () => Promise.resolve(wardrobeResponse('none', []));
  axios.get.mockResolvedValue({ data: { items: [] } });
  axios.delete.mockResolvedValue({ data: { success: true } });
  axios.post.mockImplementation((url, body) => {
    if (url.endsWith('/api/ai/similar')) return wardrobeReply();
    if (url.endsWith('/api/shop/search')) return shopReply();
    if (url.endsWith('/api/wishlist')) {
      return Promise.resolve({ data: { success: true, item: { id: 'w1', ...body } } });
    }
    return Promise.resolve({ data: {} });
  });
});

function WardrobeProbe() {
  const location = useLocation();
  return <div>WARDROBE {location.state?.openItem}</div>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/similar']}>
      <Routes>
        <Route path="/similar" element={<SimilarSearch />} />
        <Route path="/wardrobe" element={<WardrobeProbe />} />
        <Route path="/login" element={<div>LOGIN</div>} />
      </Routes>
    </MemoryRouter>
  );
}

async function upload() {
  fireEvent.change(screen.getByLabelText('Clothing photo'), { target: { files: [PHOTO] } });
  fireEvent.click(screen.getByRole('button', { name: 'Find Similar' }));
}

const shopCalls = () => axios.post.mock.calls.filter(([url]) => url.endsWith('/api/shop/search'));

test('nothing similar owned: searches shops automatically and labels products honestly', async () => {
  renderPage();
  await upload();

  expect(await screen.findByText('Pink Embroidered Kurta')).toBeInTheDocument();
  expect(screen.getByAltText('Your uploaded clothing')).toHaveAttribute('src', 'blob:preview');
  expect(shopCalls()).toHaveLength(1);

  const cards = screen.getAllByTestId('product-card');
  expect(within(cards[0]).getByText('Exact product match')).toBeInTheDocument();
  expect(within(cards[1]).getByText('Similar style')).toBeInTheDocument();
  expect(within(cards[2]).getByText('Same category')).toBeInTheDocument();
  expect(within(cards[2]).getByText('Out of stock')).toBeInTheDocument();
  expect(within(cards[2]).getByLabelText('No image available')).toBeInTheDocument();

  const view = within(cards[0]).getByRole('link', { name: /View Product/ });
  expect(view).toHaveAttribute('href', 'https://www.ajio.com/p/1');
  expect(view).toHaveAttribute('target', '_blank');
  expect(view).toHaveAttribute('rel', 'noopener noreferrer');

  expect(screen.getByRole('link', { name: 'Myntra ↗' })).toHaveAttribute('href', LINKS[0].url);

  // The detected attributes went along with the photo.
  const sent = shopCalls()[0][1];
  expect(JSON.parse(sent.get('analysis')).category).toBe('kurta');
  expect(sent.get('image')).toBe(PHOTO);
});

test('owning something very close: no automatic shop search, offered with a button', async () => {
  wardrobeReply = () => Promise.resolve(wardrobeResponse('very_close', [
    { item_id: 'w9', image: 'https://img/w.jpg', category: 'Kurta', color: 'pink', similarity: 0.93, match_level: 'very_close' },
  ]));
  renderPage();
  await upload();

  expect(await screen.findByText('You probably own this already.')).toBeInTheDocument();
  expect(screen.getByText('93.0% visual similarity')).toBeInTheDocument();
  expect(shopCalls()).toHaveLength(0);

  fireEvent.click(screen.getByRole('button', { name: 'Show online alternatives' }));
  expect(await screen.findByText('Pink Straight Kurta')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'View in wardrobe' }));
  expect(await screen.findByText('WARDROBE w9')).toBeInTheDocument();
});

test('no product search available: shop links instead of fake products', async () => {
  shopReply = () => Promise.resolve(shopResponse({
    status: 'links_only', products: [],
    message: "Product search isn't set up on this server yet, so here are searches for this look on each shop.",
  }));
  renderPage();
  await upload();

  expect(await screen.findByText(/isn't set up on this server/)).toBeInTheDocument();
  expect(screen.queryAllByTestId('product-card')).toHaveLength(0);
  expect(screen.getByRole('link', { name: 'AJIO ↗' })).toBeInTheDocument();
});

test('a failed shop search can be retried', async () => {
  shopReply = () => Promise.reject({ response: { status: 500, data: { message: 'Shop search broke.' } } });
  renderPage();
  await upload();

  expect(await screen.findByText('Shop search broke.')).toBeInTheDocument();
  shopReply = () => Promise.resolve(shopResponse());
  fireEvent.click(screen.getAllByRole('button', { name: 'Retry' })[0]);
  expect(await screen.findByText('Pink Embroidered Kurta')).toBeInTheDocument();
});

test('edited keywords are sent with the next shop search', async () => {
  renderPage();
  await upload();
  await screen.findByText('Pink Embroidered Kurta');

  fireEvent.change(screen.getByPlaceholderText('e.g. yellow anarkali mirror work'), { target: { value: 'pink chikankari kurta' } });
  fireEvent.change(screen.getAllByPlaceholderText('unknown')[0], { target: { value: 'kurti' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search shops again' }));

  await waitFor(() => expect(shopCalls()).toHaveLength(2));
  const sent = JSON.parse(shopCalls()[1][1].get('analysis'));
  expect(sent.keywords).toBe('pink chikankari kurta');
  expect(sent.category).toBe('kurti');
  expect(sent.sources.category).toBe('you');
});

test('filters and price sorting work on the shown products', async () => {
  renderPage();
  await upload();
  await screen.findByText('Pink Embroidered Kurta');

  fireEvent.click(screen.getByRole('button', { name: 'Myntra' }));
  expect(screen.getAllByTestId('product-card')).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));

  fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'price_low' } });
  const titles = screen.getAllByTestId('product-card').map((c) => within(c).getByText(/Kurta$/).textContent);
  expect(titles).toEqual(['Pink Straight Kurta', 'Pink Embroidered Kurta', 'Blue Kurta']);

  fireEvent.change(screen.getByLabelText('Maximum price'), { target: { value: '1000' } });
  expect(screen.getAllByTestId('product-card')).toHaveLength(1);
});

test('wishlist save and compare', async () => {
  renderPage();
  await upload();
  await screen.findByText('Pink Embroidered Kurta');

  const cards = screen.getAllByTestId('product-card');
  fireEvent.click(within(cards[0]).getByRole('button', { name: 'Save to wishlist' }));
  expect(await within(cards[0]).findByRole('button', { name: 'Remove from wishlist' })).toBeInTheDocument();
  const saved = axios.post.mock.calls.find(([url]) => url.endsWith('/api/wishlist'))[1];
  expect(saved).toEqual(expect.objectContaining({ url: 'https://www.ajio.com/p/1', title: 'Pink Embroidered Kurta' }));
  expect(screen.getByRole('button', { name: /Your shopping wishlist \(1\)/ })).toBeInTheDocument();

  fireEvent.click(within(cards[0]).getByLabelText('Compare'));
  fireEvent.click(within(cards[1]).getByLabelText('Compare'));
  const table = screen.getByRole('region', { name: 'Compare products' });
  expect(within(table).getByText('Compare (2/3)')).toBeInTheDocument();
  expect(within(table).getByText('₹1,499')).toBeInTheDocument();
  expect(within(table).getByText('₹899')).toBeInTheDocument();
});

test('price formatting', () => {
  expect(formatPrice({ price: 1499, currency: 'INR' })).toBe('₹1,499');
  expect(formatPrice({ price: null, price_text: '$20' })).toBe('$20');
  expect(formatPrice({})).toBe('');
});
