"""Vendor CAD acquisition and content-addressed cache (standard library only).

Run ``python -m PyOpticL.vendor_cad --help`` outside FreeCAD.
Dynamic product pages may require a browser download followed by register.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


VENDORS = {
    "thorlabs": ("thorlabs.com", "thorlabs.us", "thorlabs.de", "thorlabs.co.jp"),
    "optosigma": ("optosigma.com", "sigma-koki.com"),
}
MAX_BYTES = 100 * 1024 * 1024


class BrowserRequired(RuntimeError):
    pass


def cache_root():
    return Path(os.environ.get("PYOPTICL_CAD_CACHE", Path.home() / ".cache" / "pyopticl" / "cad"))


def check_url(vendor, url):
    parsed = urlparse(url)
    if vendor not in VENDORS or parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("An official HTTPS vendor URL is required")
    host = (parsed.hostname or "").lower()
    if not any(host == domain or host.endswith("." + domain) for domain in VENDORS[vendor]):
        raise ValueError(f"URL is not on an official {vendor} domain: {host}")
    return url


def fetch(vendor, url):
    check_url(vendor, url)
    request = Request(url, headers={"User-Agent": "PyOpticL-CAD/1.0"})
    with urlopen(request, timeout=30) as response:
        resolved = response.geturl()
        check_url(vendor, resolved)
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Asset exceeds 100 MiB limit")
    return data, resolved


def validate(data, kind):
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Empty or oversized asset")
    if kind == "step":
        text = data.decode("latin1")
        if not text.lstrip().startswith("ISO-10303-21;") or "END-ISO-10303-21;" not in text:
            raise ValueError("Not a complete STEP exchange file")
        if "DATA;" not in text or "FILE_SCHEMA" not in text:
            raise ValueError("STEP is missing header or data sections")
    elif kind == "pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-4096:]:
            raise ValueError("Not a complete PDF document")
    else:
        raise ValueError("Only STEP and PDF are supported")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs = dict(attrs)
            if attrs.get("href"):
                self.urls.append(attrs["href"])


def discover(vendor, part, product_url):
    """Use public links only. No guessed filenames or undocumented API calls."""
    data, resolved = fetch(vendor, product_url)
    parser = Links()
    parser.feed(data.decode("utf-8", errors="replace"))
    result = []
    for href in parser.urls:
        url = urljoin(resolved, href)
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix in (".step", ".stp", ".pdf"):
            check_url(vendor, url)
            # Restrict automatic discovery to links identifying the exact part.
            if part.casefold() in url.casefold():
                result.append({"kind": "pdf" if suffix == ".pdf" else "step", "url": url})
    if not result:
        raise BrowserRequired("No exact-part public CAD links found. Download STEP/drawing from the product page in a browser, then register the files.")
    return result


def register(vendor, part, product_url, data, filename, kind, *, asset_url=None,
             document_id=None, root=None, revision=None):
    check_url(vendor, product_url)
    if asset_url:
        check_url(vendor, asset_url)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+/-]*", part) or ".." in part:
        raise ValueError("Invalid part number")
    filename = Path(filename).name
    identifiers = (part, document_id) if document_id else (part,)
    if not any(token and token.casefold() in filename.casefold() for token in identifiers):
        raise ValueError("Filename does not identify the part; supply its vendor document ID from the product page")
    validate(data, kind)
    digest = hashlib.sha256(data).hexdigest()
    root = Path(root) if root else cache_root()
    directory = root / "objects" / digest
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / ("source.step" if kind == "step" else "source.pdf")
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise ValueError("Cached asset is corrupt")
    else:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as f:
            temporary = Path(f.name)
            f.write(data)
        temporary.replace(destination)
    record = {
        "schema_version": 1, "vendor": vendor, "part_number": part,
        "product_url": product_url, "asset_url": asset_url,
        "vendor_filename": filename, "document_id": document_id, "revision": revision,
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "sha256": digest,
        "kind": kind, "cache_path": destination.relative_to(root).as_posix(),
        "units": "requires_cad_inspection" if kind == "step" else None,
        "identity_evidence": "product-page document association; not inferred from shape",
    }
    # Each hash retains independent provenance; never replace a catalog pin.
    record_path = directory / (re.sub(r"[^A-Za-z0-9_.-]", "_", part) + ".json")
    if not record_path.exists():
        record_path.write_text(json.dumps(record, indent=2) + "\n")
    return record


def resolve(record, root=None):
    if record.get("schema_version") != 1:
        raise ValueError("Unsupported asset manifest version")
    root = (Path(root) if root else cache_root()).resolve()
    path = (root / record["cache_path"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Asset path escapes cache")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError("Asset hash differs from catalog pin")
    validate(data, record["kind"])
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("discover", "download", "register", "verify"))
    parser.add_argument("--vendor", choices=tuple(VENDORS))
    parser.add_argument("--part")
    parser.add_argument("--product-url")
    parser.add_argument("--asset-url")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--kind", choices=("step", "pdf"))
    parser.add_argument("--vendor-filename")
    parser.add_argument("--document-id")
    parser.add_argument("--revision")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "verify":
            if not args.manifest:
                parser.error("verify requires --manifest")
            print(resolve(json.loads(args.manifest.read_text()), args.cache))
            return 0
        if not all((args.vendor, args.part, args.product_url)):
            parser.error("--vendor, --part and --product-url are required")
        if args.action == "discover":
            result = discover(args.vendor, args.part, args.product_url)
        else:
            if not args.kind:
                parser.error("--kind is required")
            if args.action == "download":
                if not args.asset_url:
                    parser.error("download requires --asset-url from the product page")
                data, url = fetch(args.vendor, args.asset_url)
                filename = args.vendor_filename or Path(urlparse(url).path).name
            else:
                if not args.file:
                    parser.error("register requires --file")
                data, url = args.file.read_bytes(), args.asset_url
                filename = args.vendor_filename or args.file.name
            result = register(args.vendor, args.part, args.product_url, data, filename,
                              args.kind, asset_url=url, document_id=args.document_id,
                              revision=args.revision, root=args.cache)
        output = json.dumps(result, indent=2) + "\n"
        if args.manifest:
            if args.action == "discover":
                raise ValueError("Discovery results are not asset manifests; omit --manifest")
            if args.manifest.exists() and json.loads(args.manifest.read_text()).get("sha256") != result.get("sha256"):
                raise ValueError("Existing manifest pins another asset; write a new revision instead")
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_text(output)
        print(output, end="")
        return 0
    except BrowserRequired as exc:
        print(json.dumps({"status": "browser_required", "message": str(exc)}))
        return 2
    except (ValueError, OSError) as exc:
        parser.exit(1, f"CAD acquisition failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
