"""Generate synthetic, non-photographic Phase 0 fixture files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_SIMULATED_NEF = (
    b"PHOTO_SESSION_WORKFLOW_SYNTHETIC_NEF\n"
    b"CAMERA=Nikon D7000\n"
    b"NOT_A_DECODABLE_RAW_FILE\n"
)
_SIMULATED_JPG = (
    b"PHOTO_SESSION_WORKFLOW_SYNTHETIC_JPG\n"
    b"NOT_A_DECODABLE_JPEG_IMAGE\n"
)
_XMP_PREFIX = (
    '<?xpacket begin=""?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
)
_XMP_SUFFIX = "  </rdf:RDF>\n</x:xmpmeta>\n<?xpacket end=\"w\"?>\n"


@dataclass(frozen=True, slots=True)
class SyntheticSession:
    root: Path
    files: tuple[Path, ...]
    expected_missing: tuple[Path, ...]


def _write(root: Path, relative_name: str, content: bytes) -> Path:
    destination = root / relative_name
    destination.write_bytes(content)
    return destination


def create_synthetic_session(root: Path) -> SyntheticSession:
    """Populate an empty temporary directory with non-decodable fixtures."""

    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("synthetic fixture root must be a directory")
    if any(root.iterdir()):
        raise ValueError("synthetic fixture root must be empty")

    rated_xmp = (
        _XMP_PREFIX
        + '    <rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
        + 'xmp:Rating="4"/>\n'
        + _XMP_SUFFIX
    ).encode("utf-8")
    unrated_xmp = (
        _XMP_PREFIX
        + '    <rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/"/>\n'
        + _XMP_SUFFIX
    ).encode("utf-8")
    invalid_rating_xmp = (
        _XMP_PREFIX
        + '    <rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
        + 'xmp:Rating="invalid-rating"/>\n'
        + _XMP_SUFFIX
    ).encode("utf-8")

    files = (
        _write(root, "rated.NEF", _SIMULATED_NEF),
        _write(root, "rated.jpg", _SIMULATED_JPG),
        _write(root, "rated.xmp", rated_xmp),
        _write(root, "rated.acr", b"SYNTHETIC_ACR_AUXILIARY\n"),
        _write(root, "unrated.xmp", unrated_xmp),
        _write(root, "invalid-rating.xmp", invalid_rating_xmp),
        _write(root, "malformed.xmp", b"<x:xmpmeta><broken>"),
        _write(root, "ambiguous.NEF", _SIMULATED_NEF),
        _write(root, "ambiguous.jpg", _SIMULATED_JPG),
        _write(root, "ambiguous.jpeg", _SIMULATED_JPG),
        _write(root, "CASE_VARIANT.NEF", _SIMULATED_NEF),
        _write(root, "case_variant.xmp", rated_xmp),
        _write(root, "orphan.xmp", unrated_xmp),
    )
    expected_missing = (root / "missing.NEF", root / "missing.jpg")
    return SyntheticSession(root=root, files=files, expected_missing=expected_missing)
