import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import axios from 'axios';
import VerifyEmail from './VerifyEmail';
import Login from './Login';

jest.mock('axios');

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
});

function renderAt(path, state) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: path, state }]}>
      <Routes>
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/login" element={<Login />} />
        <Route path="/dashboard" element={<div>DASHBOARD</div>} />
      </Routes>
    </MemoryRouter>
  );
}

test('rejects a code that is not 6 digits without calling the server', async () => {
  renderAt('/verify-email', { email: 'new@gmail.com' });
  expect(screen.getByText('new@gmail.com')).toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText('6-digit code'), { target: { value: '12' } });
  fireEvent.click(screen.getByRole('button', { name: /verify email/i }));
  expect(await screen.findByText(/Enter the 6-digit code/)).toBeInTheDocument();
  expect(axios.post).not.toHaveBeenCalled();
});

test('a correct code goes back to login with the email pre-filled', async () => {
  axios.post.mockResolvedValue({ data: { success: true, message: 'Email verified! You can log in now.' } });
  renderAt('/verify-email', { email: 'new@gmail.com' });
  fireEvent.change(screen.getByPlaceholderText('6-digit code'), { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: /verify email/i }));
  expect(await screen.findByText('Email verified! You can log in now.')).toBeInTheDocument();
  expect(axios.post).toHaveBeenCalledWith(
    expect.stringMatching(/\/api\/verify-email$/), { email: 'new@gmail.com', code: '123456' });
  expect(screen.getByPlaceholderText('Email address')).toHaveValue('new@gmail.com');
});

test('login of an unverified account opens the verify screen and stores no token', async () => {
  axios.post.mockRejectedValue({
    response: { status: 403, data: { success: false, code: 'email_not_verified',
      email: 'new@gmail.com', message: 'Please verify your email address first.' } },
  });
  renderAt('/login');
  fireEvent.change(screen.getByPlaceholderText('Email address'), { target: { value: 'New@Gmail.com' } });
  fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'secret123' } });
  fireEvent.click(screen.getByRole('button', { name: /login/i }));
  expect(await screen.findByText('Verify Your Email')).toBeInTheDocument();
  expect(localStorage.getItem('token')).toBeNull();
  const body = axios.post.mock.calls[0][1];
  expect(body.email).toBe('new@gmail.com');
  expect(body.client).toEqual(expect.objectContaining({ timezone: expect.any(String) }));
  expect(JSON.stringify(body.client)).not.toContain('secret123');
});

test('a verified login still goes to the dashboard', async () => {
  axios.post.mockResolvedValue({ data: { success: true, token: 'tok', gender: 'Female' } });
  renderAt('/login');
  fireEvent.change(screen.getByPlaceholderText('Email address'), { target: { value: 'a@gmail.com' } });
  fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'secret123' } });
  fireEvent.click(screen.getByRole('button', { name: /login/i }));
  await waitFor(() => expect(screen.getByText('DASHBOARD')).toBeInTheDocument());
  expect(localStorage.getItem('token')).toBe('tok');
});
