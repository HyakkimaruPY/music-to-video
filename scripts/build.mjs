import { copyFile, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { build } from 'esbuild';

const root = new URL('../', import.meta.url);
const fromRoot = (...parts) => join(root.pathname, ...parts);
const output = fromRoot('_site');

await rm(output, { recursive: true, force: true });
await mkdir(join(output, 'vendor', 'ffmpeg'), { recursive: true });
await mkdir(join(output, 'vendor', 'core'), { recursive: true });

let html = await readFile(fromRoot('index.html'), 'utf8');
html = html.replace(
  'https://esm.sh/music-metadata@11.14.0?bundle',
  './vendor/music-metadata.js'
);
await writeFile(join(output, 'index.html'), html, 'utf8');
await writeFile(join(output, '.nojekyll'), '', 'utf8');

const copies = [
  ['node_modules/@ffmpeg/ffmpeg/dist/umd/ffmpeg.js', 'vendor/ffmpeg/ffmpeg.js'],
  ['node_modules/@ffmpeg/ffmpeg/dist/umd/814.ffmpeg.js', 'vendor/ffmpeg/814.ffmpeg.js'],
  ['node_modules/@ffmpeg/core/dist/umd/ffmpeg-core.js', 'vendor/core/ffmpeg-core.js'],
  ['node_modules/@ffmpeg/core/dist/umd/ffmpeg-core.wasm', 'vendor/core/ffmpeg-core.wasm']
];

for (const [source, destination] of copies) {
  const target = join(output, destination);
  await mkdir(dirname(target), { recursive: true });
  await copyFile(fromRoot(source), target);
}

await build({
  entryPoints: [fromRoot('src/music-metadata-entry.js')],
  outfile: join(output, 'vendor', 'music-metadata.js'),
  bundle: true,
  minify: true,
  format: 'esm',
  platform: 'browser',
  target: ['chrome109', 'firefox115', 'safari16'],
  legalComments: 'eof'
});

console.log('Site pronto em _site/ com todas as dependências locais.');
