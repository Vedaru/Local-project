# web_fetcher_rs

Rust-based web article extractor for Local Project.

## Build

```powershell
cd rust_modules/web_fetcher_rs
cargo build --release
```

If your machine does not have the MSVC linker (`link.exe`), use GNU toolchain + self-contained linker:

```powershell
$env:RUSTFLAGS="-Clinker=rust-lld -Clink-self-contained=yes"
cargo +stable-x86_64-pc-windows-gnu build --release
```

Or run the helper script from project root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_web_fetcher_rs.ps1
```

The output binary path on Windows:

- rust_modules/web_fetcher_rs/target/release/web_fetcher_rs.exe

## Usage

```powershell
web_fetcher_rs --url "https://example.com" --timeout 12 --max-chars 10000
```

The tool prints JSON:

```json
{
  "success": true,
  "source": "rust_static",
  "content": "...",
  "error": null
}
```

## Python Integration

`WebContentFetcher` in `modules/openmanus/app/tool/web_search.py` first tries to import the Python extension (`_web_fetcher_rs`) for direct in-process calls.

Binary fallback is optional and controlled by environment variable:

- `WEB_FETCHER_RS_ENABLE_BIN_FALLBACK=1` enables fallback to executable mode.
- if not set, direct extension mode is used and binary fallback is skipped.

When binary fallback is enabled, the executable is discovered in this order:

1. `WEB_FETCHER_RS_BIN` environment variable
2. executable found in `PATH`
3. default local build output paths under `rust_modules/web_fetcher_rs/target/`

The web content path is Rust-first and Rust-only by design. If the Rust binary is unavailable or fails, no Python extractor fallback is used.
