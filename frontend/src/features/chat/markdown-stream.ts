// Streaming markdown can end mid-construct (unclosed **bold**, `code`,
// [link](, or a table row without its closing pipe). Rendering those
// half-open constructs flickers badly, so during streaming we trim the
// trailing incomplete construct and render it once its closer arrives.

/** Collect byte ranges [start, end) of all complete code spans in `text`. */
function codeSpanRanges(text: string): Array<[number, number]> {
  const ranges: Array<[number, number]> = [];
  for (const m of text.matchAll(/`[^`]*`/g)) {
    ranges.push([m.index, m.index + m[0].length]);
  }
  return ranges;
}

/** Returns true if position `pos` falls inside one of the given ranges. */
function insideRanges(pos: number, ranges: Array<[number, number]>): boolean {
  return ranges.some(([start, end]) => pos >= start && pos < end);
}

/**
 * Find the last occurrence of `needle` in `text` that falls OUTSIDE every
 * range in `ranges`. Returns -1 when none found.
 */
function lastIndexOutsideRanges(
  text: string,
  needle: string,
  ranges: Array<[number, number]>,
): number {
  let idx = text.lastIndexOf(needle);
  while (idx !== -1 && insideRanges(idx, ranges)) {
    idx = text.lastIndexOf(needle, idx - 1);
  }
  return idx;
}

export function stabilizeStreamingMarkdown(text: string): string {
  let out = text;

  // Trailing incomplete link: last '[' (outside complete code spans, and not
  // backslash-escaped) whose remainder never completes '](...)'.
  const spans = codeSpanRanges(out);
  const lastOpenBracket = lastIndexOutsideRanges(out, '[', spans);
  if (lastOpenBracket !== -1 && out[lastOpenBracket - 1] !== '\\') {
    const rest = out.slice(lastOpenBracket);
    if (!/\]\([^)]*\)/.test(rest)) {
      if (!/\]/.test(rest) || /\]\([^)]*$/.test(rest)) {
        out = out.slice(0, lastOpenBracket);
      }
    }
  }

  // Unclosed inline code span
  const ticks = (out.match(/`/g) || []).length;
  if (ticks % 2 === 1) out = out.slice(0, out.lastIndexOf('`'));

  // Unclosed bold marker — ignore '**' inside complete code spans, which are
  // literal text to markdown. If parity outside code spans is odd, trim at
  // the last outside '**'.
  const boldSpans = codeSpanRanges(out);
  const boldMatches = [...out.matchAll(/\*\*/g)].filter((m) => !insideRanges(m.index, boldSpans));
  if (boldMatches.length % 2 === 1) {
    const lastBoldIdx = boldMatches[boldMatches.length - 1].index;
    out = out.slice(0, lastBoldIdx);
  }

  // Trailing table row missing its closing pipe
  const nl = out.lastIndexOf('\n');
  const lastLine = out.slice(nl + 1);
  if (lastLine.startsWith('|') && !lastLine.trimEnd().endsWith('|')) {
    out = out.slice(0, nl + 1);
  }

  return out;
}
