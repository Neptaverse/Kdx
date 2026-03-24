# Contributing

## Development setup

```bash
git clone https://github.com/Neptaverse/Kdx.git
cd Kdx
python bootstrap.py --setup-only
```

Run the test suite:

```bash
python bootstrap.py --python -m unittest discover -s tests -v
```

Build the package locally:

```bash
python bootstrap.py --python -m pip install build
python bootstrap.py --python -m build
```

## Pull requests

- Keep changes narrowly scoped.
- Add or update tests for behavior changes.
- Preserve cross-platform behavior for Linux, macOS, and Windows.
- Do not commit `.venv/`, `.kdx/`, `.bench/`, or generated package metadata.
