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
- creates a **GitHub Release** with auto-generated notes (the tarball used by Homebrew).

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

## 3. Homebrew tap

The tap lives at `insideaayush/homebrew-tap`, formula `Formula/chat-memory-sync.rb`.
After a GitHub release exists, update the formula to the new tag + source tarball sha256:

```bash
VER=0.1.0
URL="https://github.com/insideaayush/chat-memory-sync/archive/refs/tags/v${VER}.tar.gz"
SHA=$(curl -sL "$URL" | shasum -a 256 | awk '{print $1}')
# edit Formula/chat-memory-sync.rb -> url + sha256 + version, commit & push the tap
```

Users install with:

```bash
brew install insideaayush/tap/chat-memory-sync
```

## Versioning

Semantic-ish. Bump minor for new harnesses/features, patch for fixes. Adapters are
additive and low-risk; prefer frequent small releases.
