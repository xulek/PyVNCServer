# Modern RFB extensions in PyVNCServer 3.4

## ContinuousUpdates

Clients advertise the pseudo-encoding `-313`. PyVNCServer answers with message type `150` (`EndOfContinuousUpdates`) to announce support.

The client can then send:

```text
type:   150
enable: 1
x/y/w/h: requested streaming region
```

While enabled, the server sends framebuffer updates without waiting for another `FramebufferUpdateRequest`.

Implementation details:

- streaming stays inside the per-client session thread;
- stateful encoders such as Tight and Zlib are never driven concurrently;
- socket polling is aligned with the connection's target frame rate;
- input traffic cannot indefinitely starve framebuffer delivery;
- unchanged producer generations do not generate empty framebuffer traffic unless a cursor pseudo-rectangle needs to be sent.

Disabling ContinuousUpdates sends a one-byte EndOfContinuousUpdates confirmation.

## Fence

Clients advertise `-312`.

PyVNCServer sends a small server-side fence request after negotiation. The extension uses message type `248` in both directions.

Supported flags:

- BlockBefore
- BlockAfter
- SyncNext is parsed but not implemented as a deferred execution barrier
- Request

Fence payloads are limited to 64 bytes.

BlockBefore and BlockAfter are naturally satisfied because the client message loop is synchronous.

## LastRect

Clients advertise `-224`.

When enabled with:

```toml
[features]
enable_last_rect = true
```

FramebufferUpdate uses a rectangle count of `0xffff` and appends:

```text
x=0 y=0 w=0 h=0 encoding=-224
```

It is disabled by default for conservative compatibility with older viewers.

## ExtendedDesktopSize

Clients advertise `-308`.

PyVNCServer immediately sends the current layout after negotiation, allowing clients such as noVNC to discover SetDesktopSize support.

Each screen is encoded as exactly 16 bytes:

```text
CARD32 id
CARD16 x
CARD16 y
CARD16 width
CARD16 height
CARD32 flags
```

Framebuffer size changes use the rectangle header fields as required by the extension:

- `x`: resize reason
- `y`: status
- `width` / `height`: new framebuffer size
- `encoding`: `-308`

Client SetDesktopSize requests use message type `251`.

By default host-side resize is rejected with status `1` (administratively prohibited). PyVNCServer does not pretend to change the physical Windows display mode.

## Compatibility policy

A pseudo-encoding is only used after the client explicitly advertises it in SetEncodings.

The v3.4 features are intended to be additive. Existing Raw/RRE/Hextile/Zlib/Tight/ZRLE clients continue to use the previous request/response path when they do not negotiate these extensions.
