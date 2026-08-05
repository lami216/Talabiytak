from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "app" / "static" / "branding"
SOURCE = BRANDING / "talabiytak-logo-source.png"
OUTPUTS = {
    "talabiytak-logo-48.png": 48,
    "talabiytak-favicon-32.png": 32,
    "talabiytak-apple-touch-180.png": 180,
    "talabiytak-icon-192.png": 192,
    "talabiytak-icon-512.png": 512,
}
MASKABLE = BRANDING / "talabiytak-maskable-512.png"


def load_source() -> Image.Image:
    if not SOURCE.exists():
        raise SystemExit(f"Missing required source logo: {SOURCE}")
    image = Image.open(SOURCE).convert("RGBA")
    if image.width != image.height:
        raise SystemExit("talabiytak-logo-source.png must be square")
    return image


def contain(image: Image.Image, size: int) -> Image.Image:
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    copy = image.copy()
    copy.thumbnail((size, size), Image.Resampling.LANCZOS)
    result.alpha_composite(copy, ((size - copy.width) // 2, (size - copy.height) // 2))
    return result


def build_maskable(image: Image.Image) -> Image.Image:
    result = Image.new("RGBA", (512, 512), "#0b5d4b")
    safe = image.copy()
    safe.thumbnail((328, 328), Image.Resampling.LANCZOS)
    result.alpha_composite(safe, ((512 - safe.width) // 2, (512 - safe.height) // 2))
    return result


def main() -> None:
    BRANDING.mkdir(parents=True, exist_ok=True)
    source = load_source()
    for filename, size in OUTPUTS.items():
        contain(source, size).save(BRANDING / filename, "PNG", optimize=True)
    build_maskable(source).save(MASKABLE, "PNG", optimize=True)


if __name__ == "__main__":
    main()
