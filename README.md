# Aura — Música para Vídeo · GitHub Pages v1.2

Este pacote corrige o erro `FFmpegUtil não apareceu` e publica o site com as dependências hospedadas no próprio GitHub Pages.

## Publicação

1. Envie **todo o conteúdo desta pasta** para a raiz do repositório.
2. Abra **Settings → Pages**.
3. Em **Build and deployment → Source**, selecione **GitHub Actions**.
4. Abra a aba **Actions** e acompanhe o workflow **Publicar Aura no GitHub Pages**.

O workflow executa `npm install`, monta `_site/` e inclui localmente:

- `@ffmpeg/ffmpeg`;
- o worker `814.ffmpeg.js`;
- `ffmpeg-core.js`;
- `ffmpeg-core.wasm`;
- um bundle local de `music-metadata`.

Assim, o navegador não depende de `FFmpegUtil` nem precisa buscar os arquivos principais em CDNs durante a exportação.

## Teste local opcional

```bash
npm install
npm run build
npx serve _site
```

A pasta `_site/` é gerada automaticamente e não precisa ser enviada ao repositório.
