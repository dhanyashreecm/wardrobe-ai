import { apiErrorMessage, isAuthError, outfitTags } from './api';

describe('apiErrorMessage', () => {
  test('server unreachable says so', () => {
    expect(apiErrorMessage(new Error('Network Error'), 'Upload')).toMatch(/can't reach the server/);
  });

  test('expired session shows the backend message', () => {
    const err = { response: { status: 401, data: { message: 'Your session has expired - please log in again.' } } };
    expect(apiErrorMessage(err, 'Upload')).toMatch(/session has expired/);
    expect(isAuthError(err)).toBe(true);
  });

  test('uses message, then error, then msg', () => {
    expect(apiErrorMessage({ response: { status: 502, data: { message: 'Upload failed: the image could not be stored' } } }))
      .toMatch(/could not be stored/);
    expect(apiErrorMessage({ response: { status: 400, data: { error: 'bad colour' } } })).toBe('bad colour');
    expect(apiErrorMessage({ response: { status: 401, data: { msg: 'Token has expired' } } })).toMatch(/expired/);
  });

  test('never a bare "Upload failed."', () => {
    const msg = apiErrorMessage({ response: { status: 500, data: '<html>' } }, 'Upload');
    expect(msg).toMatch(/server error 500/);
  });
});

test('outfitTags removes duplicates', () => {
  expect(outfitTags({ occasion: 'party', style_tags: ['Party', 'Smart'] })).toBe('Party • Smart');
});
