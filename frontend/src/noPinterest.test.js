// Inspiration is shown as pictures only: no Pinterest name, links,
// buttons or URLs anywhere in the app's code.
const fs = require('fs');
const path = require('path');

function sources(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sources(full);
    return /\.(js|jsx|css)$/.test(entry.name) && !/\.test\./.test(entry.name) ? [full] : [];
  });
}

test('no Pinterest links, names or URLs in the app', () => {
  const offenders = sources(__dirname).filter((file) =>
    /pinterest|pinimg|pin\.it/i.test(fs.readFileSync(file, 'utf8')));
  expect(offenders).toEqual([]);
});

test('the inspiration section renders images, never links', () => {
  const code = fs.readFileSync(path.join(__dirname, 'components', 'Inspiration.js'), 'utf8');
  expect(code).not.toMatch(/<a[\s>]/);
  expect(code).not.toMatch(/href=/);
});
