# UltraVNC

UltraVNC Viewer is an important interoperability target for PyVNCServer. The server negotiates RFB 3.8 and only chooses rectangle encodings advertised by the client.

## Recommended first connection

1. Start PyVNCServer locally.
2. Connect UltraVNC Viewer to `127.0.0.1:5900`.
3. Use **Auto** first.
4. If you are comparing encodings, test them one at a time after the baseline session works.

## Encoding notes

### Tight

PyVNCServer includes compatibility work for two failure modes that matter in practice:

- a rectangle must not be classified as Tight `FILL` unless it is actually uniform;
- zlib stream reset state must stay synchronized with the Tight control byte when encoder state changes.

If an UltraVNC session stops repainting only when Tight is selected, enable debug logging and try:

```toml
[features]
tight_stream_reset_for_ultravnc = true
```

This is a compatibility switch, not a blanket recommendation.

As a last-resort diagnostic:

```toml
[limits]
tight_disable_for_ultravnc = true
```

If the problem disappears, capture the negotiation/update logs and compare the next selected encoding.

### RRE

RRE payloads begin with the subrectangle count and background pixel. Raw pixel bytes therefore cannot legally be returned while the rectangle header still advertises RRE.

PyVNCServer avoids that stream-desynchronization failure by keeping the payload encoding ID consistent with the bytes actually emitted. Large RRE candidates are tiled so an individual tile can safely fall back to another negotiated encoding.

### ZRLE / Hextile / Zlib / Raw

These are useful control encodings when isolating a compatibility problem:

- **Raw**: simplest protocol baseline, highest bandwidth;
- **Hextile**: compatibility-oriented tiled encoding;
- **Zlib**: compressed full rectangles;
- **ZRLE**: tiled zlib/RLE, usually a good general-purpose option.

## v3.3 interoperability regression suite

Version 3.3 adds a real TCP/RFB regression test that keeps one connection open while changing the advertised encoding set. The test parses the actual rectangle payload rather than only checking that the socket remained connected.

The automated sequence is:

```text
Raw → RRE → Hextile → Zlib → ZRLE → Tight → Raw
```

For each step it verifies the rectangle header encoding ID and the corresponding wire format. This specifically guards against failures such as advertising RRE while sending Raw bytes, stale zlib state after an encoding switch, or a connection reset caused by stream desynchronization.

This test is not a substitute for running the UltraVNC binary itself: client-specific decoder behavior still needs manual validation before a release. It does, however, make the protocol-level failure modes reproducible in Linux and Windows CI.

## What to log

Run:

```bash
pyvncserver serve --log-level DEBUG
```

Useful lines include:

- client RFB version;
- pixel format;
- advertised encoding preference order;
- negotiated rectangle encodings;
- selected encoding per update/region;
- socket reset/timeout messages.

## Suggested manual compatibility matrix

After a code change to an encoder, test a single UltraVNC connection while switching in this order:

```text
Raw → Hextile → Zlib → ZRLE → Tight → RRE → Auto
```

Also test reconnecting with each encoding selected from the start. State-related bugs can differ between an in-session switch and a fresh connection.
