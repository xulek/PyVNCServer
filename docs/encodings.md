# Encoding reference

RFB clients advertise encoding IDs in `SetEncodings`. PyVNCServer chooses from the intersection of client-advertised and server-implemented encodings.

| Encoding | ID | Characteristics | Good for |
| --- | ---: | --- | --- |
| Raw | `0` | no compression, simplest decoder path | debugging, fast LANs, baseline testing |
| CopyRect | `1` | copies an existing framebuffer region | moves/scroll-like updates when metadata is available |
| RRE | `2` | background + colored subrectangles | flat/simple regions |
| Hextile | `5` | 16×16 tile-oriented encoding | broad compatibility |
| Zlib | `6` | zlib-compressed pixel rectangles | general compressed updates |
| Tight | `7` | Tight control/filter model + zlib/JPEG paths | common VNC viewers, mixed content |
| ZRLE | `16` | 64×64 tiles + palette/RLE + zlib | strong general-purpose compression |

Optional JPEG and H.264 paths exist as extension/feature paths and require compatible client behavior.

## Adaptive selection

The server can select different encodings for different changed regions. Selection considers:

- what the client advertised;
- connection/network profile;
- region area and dimensions;
- content characteristics;
- configured thresholds;
- optional codec availability.

Adaptive selection never makes an unsupported encoding legal: the client capability list remains the upper bound.

## Correct fallback semantics

A framebuffer rectangle header carries the encoding ID. If an encoder decides its representation is inefficient and falls back, **the emitted encoding ID must change with the payload**.

This is particularly important for RRE. A Raw payload behind an RRE header causes the client to interpret the first pixel bytes as RRE metadata and usually destroys stream synchronization.

## Tight state

Tight uses four logical zlib streams. The low bits of the compression-control byte can reset those streams. The encoder and client must agree on resets across consecutive rectangles and encoding transitions.

## ZRLE

ZRLE operates on tiles and can choose raw, solid, palette, packed-palette or RLE-style tile representations before zlib compression. The implementation includes optimized 32bpp paths and adaptive compression strategy selection.

## Benchmark

```bash
PYTHONPATH=src python benchmarks/benchmark_encoders.py
```

Microbenchmarks are useful for regression detection, but end-to-end performance also depends on capture cost, changed-region size, socket behavior and the viewer's update request cadence.
