import { render, screen } from '@testing-library/react';
import App from './App';

// Replaces the Create React App placeholder ("learn react"), which never
// matched this app. A logged-out visitor lands on the login page.
test('shows the login page when logged out', () => {
  localStorage.clear();
  window.history.pushState({}, '', '/');
  render(<App />);
  expect(screen.getByText(/welcome back/i)).toBeInTheDocument();
});
