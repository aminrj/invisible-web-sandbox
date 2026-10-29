// detect.js
//
// Ground-truth detector for text present in a web page but not visible to a
// human reader. Runs inside the page (injected by extract.py via
// page.evaluate). No imports, no external libraries.
//
// Exported as detectInvisibleText(). When loaded under Node (e.g. for
// unit testing with jsdom) module.exports is set at the bottom of the file.

function detectInvisibleText() {
  // ---------------------------------------------------------------------
  // Constants (also echoed into meta so the run is self-describing/auditable)
  // ---------------------------------------------------------------------
  const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "HEAD"]);
  const DATA_ATTR_MIN_TOKENS = 3;
  const DATA_ATTR_MIN_CHARS = 20;
  const CAMOUFLAGE_THRESHOLD = 12;
  const TEXT_CAP = 300;

  // Zero-width space, zero-width non-joiner, zero-width joiner, word joiner, BOM.
  const ZERO_WIDTH_CHARS = ["\u200B", "\u200C", "\u200D", "\u2060", "\uFEFF"];
  // U+202A-U+202E (embeds/overrides/pop) and U+2066-U+2069 (isolates/pop)
  const BIDI_RANGES = [
    [0x202a, 0x202e],
    [0x2066, 0x2069],
  ];

  const SIMPLE_ATTRS = ["alt", "aria-label", "aria-description", "aria-roledescription", "title", "placeholder"];

  const REASON = {
    CSS_SUPPRESSION: "visual-concealment/css-rendering-suppression",
    ZERO_SIZE: "visual-concealment/zero-sizing",
    OFFSCREEN: "visual-concealment/off-screen-positioning",
    TRANSPARENT: "visual-concealment/transparency",
    CAMOUFLAGE: "visual-concealment/camouflage",
    ATTR_CLOAK: "obfuscation/html-attribute-cloaking",
    CLIP: "obfuscation/clip",
    DYNAMIC: "dynamic-execution",
    COMMENT: "markup/html-comment",
    ZERO_WIDTH: "unicode/invisible-characters",
    BIDI: "unicode/bidi-override",
  };

  // ---------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------

  function wordCount(text) {
    const trimmed = text.trim();
    if (trimmed === "") return 0;
    return trimmed.split(/\s+/).length;
  }

  function capText(text) {
    const trimmed = text.trim();
    return trimmed.length > TEXT_CAP ? trimmed.slice(0, TEXT_CAP) : trimmed;
  }

  function dedupKey(text) {
    return text.trim().toLowerCase().replace(/\s+/g, " ");
  }

  // Crosses shadow-DOM boundaries: the parent of a node whose root is a
  // ShadowRoot is that shadow root's host, not null.
  function parentOrHost(node) {
    if (node.parentElement) return node.parentElement;
    const root = node.getRootNode();
    if (typeof ShadowRoot !== "undefined" && root instanceof ShadowRoot) {
      return root.host;
    }
    return null;
  }

  function* ancestorsOf(el) {
    let cur = el;
    while (cur) {
      yield cur;
      cur = parentOrHost(cur);
    }
  }

  function parseColor(colorStr) {
    if (!colorStr) return null;
    const m = colorStr.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)/i);
    if (!m) return null;
    return {
      r: parseFloat(m[1]),
      g: parseFloat(m[2]),
      b: parseFloat(m[3]),
      a: m[4] === undefined ? 1 : parseFloat(m[4]),
    };
  }

  // Rect of a DOM node (Element or a Range around a text node) expressed in
  // top-level-document coordinates. offsetX/offsetY carry the cumulative
  // position of the current frame (iframe nesting) within that top-level
  // document; win is the Window that owns `node` so we read the correct
  // scrollX/scrollY for its own document.
  function rectFromClientRects(clientRectsHolder, win, offsetX, offsetY) {
    const rects = clientRectsHolder.getClientRects();
    if (rects.length === 0) return null;
    const r = clientRectsHolder.getBoundingClientRect();
    return {
      x: r.left + win.scrollX + offsetX,
      y: r.top + win.scrollY + offsetY,
      w: r.width,
      h: r.height,
    };
  }

  function elementRect(el, win, offsetX, offsetY) {
    return rectFromClientRects(el, win, offsetX, offsetY);
  }

  function textNodeRect(textNode, win, offsetX, offsetY) {
    const range = textNode.ownerDocument.createRange();
    range.selectNodeContents(textNode);
    return rectFromClientRects(range, win, offsetX, offsetY);
  }

  // clip-path heuristic: only handles the two common cloaking shapes
  // (inset() collapsing past 100%, and a zero-area polygon). Anything else
  // (e.g. px-based inset(), circle(), url()) is a known limitation.
  function clipPathCollapsesToZero(clipPath) {
    if (!clipPath || clipPath === "none") return false;

    const insetMatch = clipPath.match(/^inset\(([^)]+)\)/i);
    if (insetMatch) {
      const parts = insetMatch[1].trim().split(/\s+/);
      const pct = parts.map((p) => (p.endsWith("%") ? parseFloat(p) : NaN));
      if (pct.every((v) => !Number.isNaN(v))) {
        let top, right, bottom, left;
        if (pct.length === 1) [top, right, bottom, left] = [pct[0], pct[0], pct[0], pct[0]];
        else if (pct.length === 2) [top, right, bottom, left] = [pct[0], pct[1], pct[0], pct[1]];
        else if (pct.length === 3) [top, right, bottom, left] = [pct[0], pct[1], pct[2], pct[1]];
        else [top, right, bottom, left] = [pct[0], pct[1], pct[2], pct[3]];
        if (top + bottom >= 100 || left + right >= 100) return true;
      }
      return false;
    }

    const polygonMatch = clipPath.match(/^polygon\(([^)]+)\)/i);
    if (polygonMatch) {
      const points = polygonMatch[1].split(",").map((p) => p.trim());
      if (points.length > 0 && points.every((p) => p === points[0])) return true;
      return false;
    }

    return false;
  }

  // Returns null (rather than guessing) when a background-image was seen
  // before any resolvable background-color: background-image content is
  // ignored by design (meta.background_image_limitation), and defaulting to
  // white in that case produced false positives - light text legible over a
  // photo (a hero banner, for example) was being flagged as camouflaged
  // against an assumed-white background that was never actually there.
  function effectiveBackground(el, win) {
    let sawBackgroundImage = false;
    for (const ancestor of ancestorsOf(el)) {
      const cs = win.getComputedStyle(ancestor);
      if (cs.backgroundImage && cs.backgroundImage !== "none") sawBackgroundImage = true;
      const bg = parseColor(cs.backgroundColor);
      if (bg && bg.a > 0) return { r: bg.r, g: bg.g, b: bg.b };
    }
    if (sawBackgroundImage) return null;
    return { r: 255, g: 255, b: 255 };
  }

  const IMAGE_TAGS = new Set(["IMG", "PICTURE", "VIDEO", "CANVAS", "SVG"]);

  function isSelfOrRelated(el, candidate) {
    return candidate === el || candidate.contains(el) || el.contains(candidate);
  }

  // effectiveBackground only ever looks at el's own ancestor chain's CSS,
  // which misses two real cases: (1) a hero image behind text that's a
  // sibling/positioned <img> or <video> rather than a CSS background-image
  // (common - better for SEO/lazy-loading/responsive srcset), and (2)
  // anything else entirely unrelated to el that happens to be visually
  // stacked on top of it at measurement time - a cookie banner, a
  // newsletter popup, anything with a higher z-index. In case (2) we
  // cannot know what a human would actually perceive as the background
  // there (plain color, image, or the popup itself), so we abstain rather
  // than guess. elementsFromPoint asks the browser directly what's really
  // stacked at that point, in paint order, independent of DOM ancestry -
  // the correct tool for this, not a heuristic guess.
  //
  // Known limitation: elementsFromPoint is viewport-relative, so this only
  // sees stacked content for text currently within the viewport bounds at
  // check time (i.e. above the fold, after scroll-to-top for T1).
  // Below-the-fold text is not covered by this check.
  function backgroundIsUncertain(el, win) {
    const doc = el.ownerDocument;
    if (typeof doc.elementsFromPoint !== "function") return false;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    if (cx < 0 || cy < 0 || cx > win.innerWidth || cy > win.innerHeight) return false;

    const stack = doc.elementsFromPoint(cx, cy);

    // Something entirely unrelated to el is the topmost thing at this
    // point - a human right now sees that, not el's own background.
    const topmost = stack[0];
    if (topmost && !isSelfOrRelated(el, topmost)) return true;

    // Otherwise, look deeper in the stack for an image/video rendered
    // behind el via sibling/positioned markup rather than a CSS
    // background-image on an ancestor.
    for (const candidate of stack) {
      if (isSelfOrRelated(el, candidate)) continue;
      if (IMAGE_TAGS.has(candidate.tagName)) return true;
      const candidateBgImage = win.getComputedStyle(candidate).backgroundImage;
      if (candidateBgImage && candidateBgImage !== "none") return true;
    }
    return false;
  }

  function isCamouflaged(el, win) {
    const cs = win.getComputedStyle(el);
    const color = parseColor(cs.color);
    if (!color) return false;
    const bg = effectiveBackground(el, win);
    if (!bg) return false;
    const diff = Math.abs(color.r - bg.r) + Math.abs(color.g - bg.g) + Math.abs(color.b - bg.b);
    if (diff >= CAMOUFLAGE_THRESHOLD) return false;
    // Only pay for the expensive hit-test once a finding is actually about
    // to be flagged, not for every text node on the page.
    if (backgroundIsUncertain(el, win)) return false;
    return true;
  }

  // hidden/clip/scroll/auto all clip their box's overflow; visible (the
  // default) does not, so a zero-area box with overflow:visible does not
  // conceal children rendered outside it.
  function ancestorClipsOverflow(cs) {
    const CLIPS = new Set(["hidden", "clip", "scroll", "auto"]);
    return CLIPS.has(cs.overflowX) || CLIPS.has(cs.overflowY);
  }

  // Reasons contributed by a single ancestor element (display/visibility,
  // zero-sizing, off-screen positioning, transparency, clip). Camouflage is
  // evaluated separately (once, for the nearest ancestor only) since it is a
  // property of resolved text color vs. effective background, not something
  // that makes sense to re-check at every level of the chain.
  //
  // isTextBearingElement is true only for the nearest element ancestor (the
  // one the text node is actually inside). A zero-area *ancestor* further up
  // the chain only conceals its descendants if it also clips overflow -
  // otherwise the text can still render outside that box. The text-bearing
  // element itself has no such exemption: if font-size/line-height/its own
  // box are zero, the text has nowhere to render regardless of overflow.
  function reasonsFromAncestor(el, win, offsetX, offsetY, topDocScrollWidth, isTextBearingElement) {
    const reasons = [];
    const cs = win.getComputedStyle(el);

    if (cs.display === "none" || cs.visibility === "hidden" || cs.visibility === "collapse") {
      reasons.push(REASON.CSS_SUPPRESSION);
    }

    const rect = elementRect(el, win, offsetX, offsetY);
    const fontSize = parseFloat(cs.fontSize);
    const lineHeight = cs.lineHeight === "normal" ? NaN : parseFloat(cs.lineHeight);
    const zeroRect = rect !== null && (rect.w === 0 || rect.h === 0);
    const zeroRectConceals = isTextBearingElement ? zeroRect : zeroRect && ancestorClipsOverflow(cs);
    if (fontSize === 0 || lineHeight === 0 || zeroRectConceals) {
      reasons.push(REASON.ZERO_SIZE);
    }

    let offscreen = false;
    if (rect !== null) {
      if (rect.x + rect.w < 0) offscreen = true;
      if (rect.y + rect.h < 0) offscreen = true;
      if (rect.x > topDocScrollWidth) offscreen = true;
    }
    const textIndent = parseFloat(cs.textIndent);
    if (!Number.isNaN(textIndent) && textIndent < -999) offscreen = true;
    if (offscreen) reasons.push(REASON.OFFSCREEN);

    if (parseFloat(cs.opacity) === 0) {
      reasons.push(REASON.TRANSPARENT);
    }

    if (
      /^rect\(\s*0px,?\s*0px,?\s*0px,?\s*0px\s*\)$/i.test(cs.clip) ||
      clipPathCollapsesToZero(cs.clipPath)
    ) {
      reasons.push(REASON.CLIP);
    }

    return reasons;
  }

  function reasonsForTextNode(textNode, nearestEl, win, offsetX, offsetY, topDocScrollWidth) {
    const ordered = [];
    const seen = new Set();
    function add(reason) {
      if (!seen.has(reason)) {
        seen.add(reason);
        ordered.push(reason);
      }
    }

    if (isCamouflaged(nearestEl, win)) add(REASON.CAMOUFLAGE);

    let depth = 0;
    for (const ancestor of ancestorsOf(nearestEl)) {
      const isTextBearingElement = depth === 0;
      for (const r of reasonsFromAncestor(ancestor, win, offsetX, offsetY, topDocScrollWidth, isTextBearingElement)) {
        add(r);
      }
      depth++;
    }

    return ordered;
  }

  function countUnicode(text) {
    let zeroWidth = 0;
    let bidi = 0;
    for (const ch of text) {
      if (ZERO_WIDTH_CHARS.includes(ch)) zeroWidth++;
      const cp = ch.codePointAt(0);
      if (BIDI_RANGES.some(([lo, hi]) => cp >= lo && cp <= hi)) bidi++;
    }
    return { zeroWidth, bidi };
  }

  // ---------------------------------------------------------------------
  // Aggregate state
  // ---------------------------------------------------------------------
  const findings = [];
  const totals = {
    visible_words: 0,
    hidden_words: 0,
    attr_words: 0,
    comment_words: 0,
    zero_width_chars: 0,
    bidi_chars: 0,
    zero_width_text_nodes: 0,
    bidi_text_nodes: 0,
  };
  const meta = {
    shadow_roots_traversed: 0,
    iframes_same_origin: 0,
    iframes_cross_origin_skipped: 0,
  };

  const topDocScrollWidth = document.documentElement.scrollWidth;

  // ---------------------------------------------------------------------
  // Recursive scan of a document-like root (the main document, a shadow
  // root, or a same-origin iframe's document). offsetX/offsetY position
  // this root within top-level document coordinates.
  // ---------------------------------------------------------------------
  function hasSkippedAncestorTag(node) {
    for (const ancestor of ancestorsOf(node.parentElement || node)) {
      if (ancestor.nodeType === 1 && SKIP_TAGS.has(ancestor.tagName)) return true;
    }
    return false;
  }

  function scanTextNodes(bodyEl, win, offsetX, offsetY) {
    const walker = document.createTreeWalker(bodyEl, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (node.textContent.trim() === "") return NodeFilter.FILTER_REJECT;
        if (hasSkippedAncestorTag(node)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    let node;
    while ((node = walker.nextNode())) {
      const text = node.textContent;
      const nearestEl = node.parentElement;
      if (!nearestEl) continue;

      const { zeroWidth, bidi } = countUnicode(text);
      if (zeroWidth > 0) {
        totals.zero_width_chars += zeroWidth;
        totals.zero_width_text_nodes += 1;
      }
      if (bidi > 0) {
        totals.bidi_chars += bidi;
        totals.bidi_text_nodes += 1;
      }

      const reasons = reasonsForTextNode(node, nearestEl, win, offsetX, offsetY, topDocScrollWidth);
      const words = wordCount(text);

      if (reasons.length === 0) {
        // Otherwise-visible text. Zero-width/bidi characters inside visible
        // text do not by themselves make it a finding (see fixture marker
        // 11) - they are only tallied above.
        totals.visible_words += words;
        continue;
      }

      // Text is already hidden for a structural reason: unicode markers
      // stack onto it per the "record all reasons" rule.
      if (zeroWidth > 0) reasons.push(REASON.ZERO_WIDTH);
      if (bidi > 0) reasons.push(REASON.BIDI);

      totals.hidden_words += words;
      findings.push({
        kind: "text",
        text: capText(text),
        words,
        reasons,
        primary: reasons[0],
        tag: nearestEl.tagName,
        rect: textNodeRect(node, win, offsetX, offsetY),
        dedup_key: dedupKey(text),
      });
    }
  }

  function scanComments(bodyEl) {
    const walker = document.createTreeWalker(bodyEl, NodeFilter.SHOW_COMMENT);
    let node;
    while ((node = walker.nextNode())) {
      totals.comment_words += wordCount(node.textContent);
    }
  }

  function scanAttributes(root, win, offsetX, offsetY) {
    const elements = root.querySelectorAll("*");
    for (const el of elements) {
      for (const attrName of SIMPLE_ATTRS) {
        const value = el.getAttribute(attrName);
        if (value === null) continue;
        if (attrName === "alt" && value === "") continue;
        if (value.trim() === "") continue;
        recordAttrFinding(el, attrName, value, win, offsetX, offsetY);
      }

      for (const attr of Array.from(el.attributes)) {
        if (!attr.name.startsWith("data-")) continue;
        const value = attr.value;
        const trimmed = value.trim();
        if (trimmed === "") continue;
        const tokenCount = trimmed.split(/\s+/).length;
        if (tokenCount < DATA_ATTR_MIN_TOKENS && trimmed.length <= DATA_ATTR_MIN_CHARS) continue;
        recordAttrFinding(el, attr.name, value, win, offsetX, offsetY);
      }
    }
  }

  function recordAttrFinding(el, attrName, value, win, offsetX, offsetY) {
    const words = wordCount(value);
    totals.attr_words += words;
    findings.push({
      kind: "attr",
      text: capText(value),
      words,
      reasons: [REASON.ATTR_CLOAK],
      primary: REASON.ATTR_CLOAK,
      attr: attrName,
      tag: el.tagName,
      rect: elementRect(el, win, offsetX, offsetY),
      dedup_key: dedupKey(value),
    });
  }

  function findShadowHosts(root) {
    const hosts = [];
    for (const el of root.querySelectorAll("*")) {
      if (el.shadowRoot) hosts.push(el);
    }
    return hosts;
  }

  function findSameDocIframes(root) {
    return Array.from(root.querySelectorAll("iframe"));
  }

  function scanRoot(bodyEl, attrRoot, win, offsetX, offsetY) {
    scanTextNodes(bodyEl, win, offsetX, offsetY);
    scanComments(bodyEl);
    scanAttributes(attrRoot, win, offsetX, offsetY);

    for (const host of findShadowHosts(attrRoot)) {
      meta.shadow_roots_traversed += 1;
      const shadowRoot = host.shadowRoot;
      // Shadow content renders exactly where the host would render its
      // light-DOM children, so it shares the host's coordinate offset.
      scanRoot(shadowRoot, shadowRoot, win, offsetX, offsetY);
    }

    for (const iframe of findSameDocIframes(attrRoot)) {
      let iframeDoc;
      try {
        iframeDoc = iframe.contentDocument;
        if (!iframeDoc) throw new Error("no contentDocument");
        // Touching contentWindow.location throws for cross-origin frames.
        void iframe.contentWindow.location.href;
      } catch (e) {
        meta.iframes_cross_origin_skipped += 1;
        continue;
      }
      meta.iframes_same_origin += 1;
      const iframeRect = elementRect(iframe, win, offsetX, offsetY);
      const childOffsetX = iframeRect ? iframeRect.x : offsetX;
      const childOffsetY = iframeRect ? iframeRect.y : offsetY;
      scanRoot(iframeDoc.body, iframeDoc, iframe.contentWindow, childOffsetX, childOffsetY);
    }
  }

  scanRoot(document.body, document, window, 0, 0);

  const total = totals.visible_words + totals.hidden_words + totals.attr_words;

  return {
    meta: Object.assign(
      {
        url: location.href,
        final_url: location.href,
        title: document.title,
        timestamp: new Date().toISOString(),
        viewport: { width: window.innerWidth, height: window.innerHeight },
        data_attr_min_tokens: DATA_ATTR_MIN_TOKENS,
        data_attr_min_chars: DATA_ATTR_MIN_CHARS,
        camouflage_threshold: CAMOUFLAGE_THRESHOLD,
        background_image_limitation: true,
      },
      meta
    ),
    totals,
    findings,
    // Not part of the spec'd return shape, but harmless/useful: lets a
    // caller sanity-check hidden_share without recomputing `total`.
    _total_words: total,
  };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = detectInvisibleText;
}
