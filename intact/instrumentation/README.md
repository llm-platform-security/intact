# `intact.instrumentation`

## What the instrumentation records

The injected script keeps references to the native implementations before it wraps them:

| Write | Interfaces | Recorded as |
|---|---|---|
| Creation | `createElement`, `createElementNS`, `cloneNode`, `importNode`, `adoptNode`, `DOMParser.parseFromString`, `Range.createContextualFragment` | `creator` |
| Insertion | `appendChild`, `insertBefore`, `replaceChild` | `inserter` |
| HTML strings | `innerHTML`, `insertAdjacentHTML`, `document.write`, `document.writeln` | `creator` |
| Attributes | `setAttribute`, `setAttributeNS` | `attr_mods` |
| Resource URLs | `src` of images, scripts, and frames; `href` of `<link>` elements | `loads` |
| Text | `textContent`, `innerText`, `nodeValue`, `data`, `appendData`, `insertData` | `text_mods` |
| Listeners | `addEventListener` | `listeners` |
| Code | `eval`, `Function`; `text` and `textContent` of script elements | synthetic source URL |

- **Script labels.** A first-party script is `1p:` plus the last segment of its URL's path; an inline script in the page's HTML has its document's URL, so it is `1p:inline` only on a page at the site root (e.g., `1p:article` on `/news/article`). A third-party script is `3p:<domain><path>[?<query>]#<hash>`, where `<domain>` is the script's registrable domain and the hash is the first eight hexadecimal digits of the SHA-256 of the script's content, which CDP reports when the engine compiles the script. The label of a URL that served different content during the visit lists every hash (`#(<hash1>|<hash2>)`), and a label has no hash when CDP reported none. A party is a registrable domain (eTLD+1), computed with the Public Suffix List.
- **Unattributed writes.** A call whose stack holds no script URL, or whose first located frame runs from a `blob:` or `data:` URL, is labeled `unknown`.
- **Code without a URL.** Code passed to `eval` or `Function`, and inline scripts whose body another script sets through `text` or `textContent` and inserts with `appendChild`, `insertBefore`, or `replaceChild`, receive a synthetic source URL (`cdpprov://dynamic-eval/<hash>`, `cdpprov://dynamic-inline/<hash>`) that maps back to the script that created the code, so callbacks defined in that code, such as timers, stay attributed. In that code, the synthetic URL replaces any source URL that the page declares.
- **Parser-created elements** belong to the party of their document (`document.scope`). They have no record (`provenance` is `null`) unless a script writes to them through `setAttribute` or `setAttributeNS`, the Text row's interfaces (or a plain-text `innerHTML`), `addEventListener`, or the `src` and `href` setters, or moves them (or an ancestor) with `appendChild`, `insertBefore`, or `replaceChild`. Such a record's `creator` is `1p:inline` and its `via` is `createElement`, also in a third-party document (`adoptNode` instead records the adopting script as the creator). The writes carry the script's label in `attr_mods`, `text_mods`, `listeners`, and `inserter` (the first move only); the `src` and `href` setters record only the party of an absolute third-party URL in `loads`, without the writer.
- **Marked elements.** The script marks each element that it records with a `data-cdp-pid` attribute, which therefore appears in `attrs`.
- **Site-isolated frames** are captured through their own CDP session. Since each renderer numbers its nodes independently, frame segment *k* maps node id *i* to *k*·10⁹ + *i*. `frames` lists each segment and the `<iframe>` element that embeds it; `uncaptured_frames` lists site-isolated frames that the capture could not reach.
- **Redirects.** When a page redirects to another site, its parties are labeled against the site where it lands.
- **Requests.** A third-party request is attributed to the first script URL on the call stack that CDP reports for it. Requests that an `img.src` assignment starts carry no stack; the image's own record (`creator` and `loads`) ties them to the script. A request from code passed to `eval` or `Function` keeps that code's synthetic URL as its initiator and counts as unattributed.
