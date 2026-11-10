# Releasing

`chat-memory-sync` ships as a pure-Python package (no runtime deps) via **PyPI**
(pip/pipx) and a **Homebrew tap**.

## 1. Cut a version

1. Bump `__version__` in `src/chat_memory_sync/__init__.py`.
2. Commit, then tag and push:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

Pushing a `v*` tag triggers `.github/workflows/release.yml`, which:
- builds the sdist + wheel and publishes to **PyPI** (via Trusted Publishing — see below),
- creates a **GitHub Release** with auto-generated notes,
- **auto-bumps the Homebrew tap** formula (url + sha256 + version) — no manual step.

That's the whole release: bump the version, tag, push. ✅

## 2. One-time PyPI setup (Trusted Publishing, no tokens)

1. Create the project on PyPI (first publish can be manual: `pip install build twine &&
   python -m build && twine upload dist/*`), or reserve the name.
2. On PyPI → project → *Publishing* → add a **GitHub Actions** trusted publisher:
   - Owner: `insideaayush`  Repo: `chat-memory-sync`  Workflow: `release.yml`
     Environment: `pypi`
3. In the GitHub repo, create an Environment named `pypi`.

After that, every `v*` tag auto-publishes. Users install with:

```bash
pipx install chat-memory-sync      # or: pip install --user chat-memory-sync
```

## 3. Homebrew tap (automated)

The tap lives at `insideaayush/homebrew-tap`, formula `Formula/chat-memory-sync.rb`.
The `homebrew` job in `release.yml` updates it automatically on every tag via
[`mislav/bump-homebrew-formula-action`].

### One-time token setup

GitHub's default `GITHUB_TOKEN` can't push to another repo, so the bump job needs a PAT
with write access to the tap:

1. Create a **fine-grained PAT**: GitHub → Settings → Developer settings → Fine-grained
   tokens. Repository access: only `insideaayush/homebrew-tap`. Permissions:
   **Contents: Read and write**.
2. Add it to this repo as a secret:

   ```bash
   gh secret set HOMEBREW_TAP_TOKEN --repo insideaayush/chat-memory-sync
   # paste the PAT when prompted
   ```

After that, tagging a release auto-updates the tap. Users install with:

```bash
brew install insideaayush/tap/chat-memory-sync
```

If you ever need to bump it by hand:

```bash
VER=0.1.0
URL="https://github.com/insideaayush/chat-memory-sync/archive/refs/tags/v${VER}.tar.gz"
SHA=$(curl -sL "$URL" | shasum -a 256 | awk '{print $1}')
# edit Formula/chat-memory-sync.rb -> url + sha256, commit & push the tap
```

[`mislav/bump-homebrew-formula-action`]: https://github.com/mislav/bump-homebrew-formula-action

## Versioning

Semantic-ish. Bump minor for new harnesses/features, patch for fixes. Adapters are
additive and low-risk; prefer frequent small releases.
